import { randomUUID } from 'node:crypto'

import { posthogFile } from '@/posthog/credentials'
import { VERSION } from '@/version'

import type { Mode } from './agent'
import type { Runtime } from './runtime'

// PostHog's own project, where posthog-cli release builds send their events too.
export const DEFAULT_TELEMETRY_TOKEN = 'sTMFPsFhdP1Ssg'

const TELEMETRY_HOST = 'https://us.i.posthog.com'
// posthog-cli's timeout. A CLI must not hang on its own analytics.
const SEND_TIMEOUT_MS = 5000
const ID_FILE = 'hog-telemetry-id'

const CI_PROVIDERS: ReadonlyArray<readonly [envVar: string, provider: string]> = [
    ['GITHUB_ACTIONS', 'github-actions'],
    ['GITLAB_CI', 'gitlab'],
    ['CIRCLECI', 'circleci'],
    ['BUILDKITE', 'buildkite'],
    ['JENKINS_URL', 'jenkins'],
    ['TRAVIS', 'travis'],
    ['BITBUCKET_BUILD_NUMBER', 'bitbucket'],
    ['TF_BUILD', 'azure-pipelines'],
    ['CODEBUILD_BUILD_ID', 'aws-codebuild'],
    ['VERCEL', 'vercel'],
    ['NETLIFY', 'netlify'],
    ['EAS_BUILD', 'expo-eas'],
    ['BITRISE_IO', 'bitrise'],
    ['XCS', 'xcode-cloud'],
]

interface QueuedEvent {
    event: string
    properties: Record<string, unknown>
    timestamp: string
}

// Anonymous usage events for the PostHog team. Events carry no arguments or option values from the
// caller, only names, counts, error codes and error messages.
export class Telemetry {
    private readonly queue: QueuedEvent[] = []
    private enabled: boolean
    readonly invocationId = randomUUID()
    projectId: string | undefined
    commandName: string | undefined

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
        const distinctId = await this.installId()
        const common = this.commonProperties()
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
        const ci = CI_PROVIDERS.find(([envVar]) => env[envVar])?.[1]
        return {
            $process_person_profile: false,
            $lib: 'hog',
            $lib_version: VERSION,
            cli: 'hog',
            cli_version: VERSION,
            invocation_id: this.invocationId,
            command_name: this.commandName,
            env_id: this.projectId,
            os: process.platform,
            arch: process.arch,
            runtime_version: process.versions.bun,
            is_ci: env.CI !== undefined || ci !== undefined,
            ci_provider: ci ?? null,
            is_terminal: this.runtime.stdoutIsTTY,
            agent: this.mode.agent ?? null,
            output_format: this.mode.format,
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
