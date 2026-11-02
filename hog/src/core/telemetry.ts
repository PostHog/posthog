import { createHash, randomUUID } from 'node:crypto'

import { posthogFile, type Credentials } from '@/posthog/credentials'
import { VERSION } from '@/version'

import type { Mode } from './agent'
import type { Env, Runtime } from './runtime'

// PostHog's own project, where posthog-cli release builds send their events too.
export const DEFAULT_TELEMETRY_TOKEN = 'sTMFPsFhdP1Ssg'

const TELEMETRY_HOST = 'https://us.i.posthog.com'
// posthog-cli's timeout. A CLI must not hang on its own analytics.
const SEND_TIMEOUT_MS = 5000
const ID_FILE = 'hog-telemetry-id'
const IDENTITY_FILE = 'hog-telemetry-identity.json'
const LOOKUP_TIMEOUT_MS = 2000
const DAY_MS = 24 * 60 * 60 * 1000

type EnvCheck = (env: Env) => boolean
const has =
    (name: string): EnvCheck =>
    (env) =>
        Boolean(env[name])

// First match wins. Platforms that also set the variables of another one come first: Depot CI
// before GitHub Actions, Harness and Woodpecker before Drone. Vercel sets VERCEL outside builds too.
const CI_PROVIDERS: ReadonlyArray<readonly [provider: string, check: EnvCheck]> = [
    ['depot-ci', has('DEPOT_JOB_URL')],
    ['harness', has('HARNESS_BUILD_ID')],
    ['woodpecker', (env) => env.CI === 'woodpecker'],
    ['github-actions', has('GITHUB_ACTIONS')],
    ['gitlab', has('GITLAB_CI')],
    ['circleci', has('CIRCLECI')],
    ['buildkite', has('BUILDKITE')],
    ['jenkins', has('JENKINS_URL')],
    ['travis', has('TRAVIS')],
    ['bitbucket', has('BITBUCKET_COMMIT')],
    ['azure-pipelines', has('TF_BUILD')],
    ['aws-codebuild', has('CODEBUILD_BUILD_ARN')],
    ['google-cloud-build', has('BUILDER_OUTPUT')],
    ['vercel', (env) => Boolean(env.VERCEL && env.CI)],
    ['netlify', has('NETLIFY')],
    ['cloudflare-pages', has('CF_PAGES')],
    ['cloudflare-workers', has('WORKERS_CI')],
    ['render', has('RENDER')],
    ['railway', has('RAILWAY_SERVICE_ID')],
    ['heroku-ci', has('HEROKU_TEST_RUN_ID')],
    ['expo-eas', has('EAS_BUILD')],
    ['bitrise', has('BITRISE_IO')],
    ['xcode-cloud', has('CI_XCODE_CLOUD')],
    ['codemagic', has('CM_BUILD_ID')],
    ['semaphore', has('SEMAPHORE')],
    ['drone', has('DRONE')],
    ['teamcity', has('TEAMCITY_VERSION')],
    ['appveyor', has('APPVEYOR')],
]

// Vendors that run GitHub Actions jobs on their own machines. Some of these variables hold tokens,
// so hog only checks that they are set.
const runnerName =
    (prefix: string): EnvCheck =>
    (env) =>
        env.RUNNER_NAME?.startsWith(prefix) === true
const CI_RUNNERS: ReadonlyArray<readonly [runner: string, check: EnvCheck]> = [
    ['depot', (env) => has('DEPOT_ORG_ID')(env) || runnerName('depot-')(env)],
    ['blacksmith', has('BLACKSMITH_VM_ID')],
    ['namespace', (env) => has('NSC_CACHE_PATH')(env) || runnerName('nsc-runner-')(env)],
    ['warpbuild', has('WARPBUILD_RUNNER_VERIFICATION_TOKEN')],
    ['ubicloud', has('UBICLOUD_CACHE_URL')],
    ['runs-on', has('RUNS_ON_RUNNER_NAME')],
    ['cirun', runnerName('cirun-')],
]

export function detectCi(env: Env): { provider: string | null; runner: string | null } {
    const provider = CI_PROVIDERS.find(([, check]) => check(env))?.[0] ?? null
    const runner = CI_RUNNERS.find(([, check]) => check(env))?.[0] ?? env.RUNNER_ENVIRONMENT ?? null
    return { provider, runner }
}

interface QueuedEvent {
    event: string
    properties: Record<string, unknown>
    timestamp: string
}

interface Identity {
    distinctId?: string
    organization?: string
    project?: string
}

interface CachedIdentity extends Identity {
    checkedAt: number
}

// Only PostHog Cloud users exist in the project telemetry goes to.
function isCloudHost(host: string): boolean {
    const { hostname } = new URL(host)
    return hostname === 'posthog.com' || hostname.endsWith('.posthog.com')
}

const text = (value: unknown): string | undefined => (typeof value === 'string' && value ? value : undefined)

// Usage events for the PostHog team. They belong to the PostHog Cloud user whose key hog uses, and
// to a random install ID otherwise. Events carry no argument or option values and no error messages,
// only names, counts and error codes.
export class Telemetry {
    private readonly queue: QueuedEvent[] = []
    private enabled: boolean
    readonly invocationId = randomUUID()
    commandName: string | undefined
    credentials: (() => Promise<Credentials>) | undefined

    constructor(
        private readonly runtime: Runtime,
        private readonly mode: Mode,
        enabled: boolean
    ) {
        this.enabled = enabled && runtime.telemetryToken !== undefined
    }

    get isEnabled(): boolean {
        return this.enabled
    }

    disable(): void {
        this.enabled = false
        this.queue.length = 0
    }

    capture(event: string, properties: Record<string, unknown> = {}): void {
        if (this.enabled) {
            this.queue.push({ event, properties, timestamp: new Date(this.runtime.now()).toISOString() })
        }
    }

    async flush(debug = false): Promise<void> {
        if (!this.enabled || this.queue.length === 0) {
            return
        }
        const credentials = await this.credentials?.().catch(() => undefined)
        const identity = credentials ? await this.identity(credentials) : undefined
        const installId = await this.installId()
        const distinctId = identity?.distinctId ?? installId
        const groups = Object.fromEntries(
            Object.entries({ organization: identity?.organization, project: identity?.project }).filter(
                ([, key]) => key !== undefined
            )
        )
        const common = {
            ...this.commonProperties(),
            install_id: installId,
            // A self-hosted project ID means nothing in PostHog Cloud and would tie the install to that instance.
            env_id: credentials && isCloudHost(credentials.host) ? credentials.projectId : null,
            ...(identity?.distinctId ? {} : { $process_person_profile: false }),
            ...(Object.keys(groups).length > 0 ? { $groups: groups } : {}),
        }
        const batch = this.queue.splice(0).map(({ event, properties, timestamp }) => ({
            event,
            timestamp,
            distinct_id: distinctId,
            properties: { ...common, ...properties },
        }))
        try {
            const response = await this.runtime.fetch(new URL('/batch/', TELEMETRY_HOST), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ api_key: this.runtime.telemetryToken, batch }),
                signal: AbortSignal.timeout(SEND_TIMEOUT_MS),
            })
            if (debug) {
                this.runtime.writeStderr(`[debug] telemetry: sent ${batch.length} events, ${response.status}\n`)
            }
        } catch (error) {
            if (debug) {
                this.runtime.writeStderr(
                    `[debug] telemetry: not sent: ${error instanceof Error ? error.message : error}\n`
                )
            }
        }
    }

    private commonProperties(): Record<string, unknown> {
        const env = this.runtime.env
        const ci = detectCi(env)
        return {
            $lib: 'hog',
            $lib_version: VERSION,
            cli: 'hog',
            cli_version: VERSION,
            invocation_id: this.invocationId,
            command_name: this.commandName,
            os: process.platform,
            arch: process.arch,
            runtime_version: process.versions.bun,
            is_ci: env.CI !== undefined || ci.provider !== null,
            ci_provider: ci.provider,
            ci_runner: ci.runner,
            is_terminal: this.runtime.stdoutIsTTY,
            agent: this.mode.agent ?? null,
            output_format: this.mode.format,
        }
    }

    // Looks the user up once per key and keeps the answer for 30 days, or a day when PostHog had
    // none, so most runs send no extra request. A key without the scopes stays anonymous.
    private async identity(credentials: Credentials): Promise<Identity | undefined> {
        if (!isCloudHost(credentials.host)) {
            return undefined
        }
        let path: string
        try {
            path = posthogFile(this.runtime, IDENTITY_FILE)
        } catch {
            return undefined
        }
        const key = createHash('sha256')
            .update(`${credentials.host}\n${credentials.projectId}\n${credentials.apiKey}`)
            .digest('hex')
        let cache: Record<string, CachedIdentity> = {}
        try {
            const parsed: unknown = JSON.parse(await this.runtime.readFile(path))
            // A cache that isn't an object is broken, so hog starts a new one instead of failing the command.
            if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
                cache = parsed as Record<string, CachedIdentity>
            }
        } catch {
            // No cache yet.
        }
        const cached = cache[key]
        const now = this.runtime.now()
        if (cached && now - cached.checkedAt < (cached.distinctId ? 30 : 1) * DAY_MS) {
            return cached
        }
        const identity = await this.lookup(credentials)
        cache[key] = { ...identity, checkedAt: now }
        try {
            await this.runtime.writePrivateFile(path, JSON.stringify(cache))
        } catch {
            // Unwritable home: the next run looks it up again.
        }
        return identity
    }

    private async lookup(credentials: Credentials): Promise<Identity> {
        const get = async (path: string): Promise<Record<string, any> | undefined> => {
            try {
                const response = await this.runtime.fetch(new URL(path, credentials.host), {
                    headers: { Authorization: `Bearer ${credentials.apiKey}` },
                    signal: AbortSignal.timeout(LOOKUP_TIMEOUT_MS),
                })
                return response.ok ? ((await response.json()) as Record<string, any>) : undefined
            } catch {
                return undefined
            }
        }
        const [user, project] = await Promise.all([
            get('/api/users/@me/'),
            get(`/api/projects/${credentials.projectId}/`),
        ])
        return {
            distinctId: text(user?.distinct_id),
            organization: text(project?.organization) ?? text(user?.organization?.id),
            project: text(project?.uuid),
        }
    }

    // A random ID kept next to the credentials, so usage counts machines instead of runs. It says
    // nothing about the person. Without a home folder, each run counts on its own.
    private async installId(): Promise<string> {
        let path: string
        try {
            path = posthogFile(this.runtime, ID_FILE)
        } catch {
            return this.invocationId
        }
        try {
            const stored = (await this.runtime.readFile(path)).trim()
            if (stored) {
                return stored
            }
        } catch {
            // No ID yet.
        }
        const id = randomUUID()
        try {
            await this.runtime.writePrivateFile(path, `${id}\n`)
        } catch {
            return this.invocationId
        }
        return id
    }
}
