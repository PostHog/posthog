import { createHash, randomUUID } from 'node:crypto'
import { z } from 'zod'

import type { AccessKey } from '@/posthog/access-key'
import { posthogFile, type Credentials } from '@/posthog/credentials'
import { INGESTION_HOSTS } from '@/posthog/host'
import { VERSION } from '@/version'

import type { Mode } from './agent'
import { detectCi, isRunningInCI } from './ci'
import { parseJsonOrUndefined } from './json'
import type { Runtime } from './runtime'
import type { Schema } from './schema'

// PostHog's own project, where posthog-cli release builds send their events too.
export const DEFAULT_TELEMETRY_TOKEN = 'sTMFPsFhdP1Ssg'

const TELEMETRY_HOST = INGESTION_HOSTS.us
// posthog-cli's timeout. A CLI must not hang on its own analytics.
const SEND_TIMEOUT_MS = 5000
const ID_FILE = 'hog-telemetry-id'
const IDENTITY_FILE = 'hog-telemetry-identity.json'
const LOOKUP_TIMEOUT_MS = 2000
const DAY_MS = 24 * 60 * 60 * 1000

interface QueuedEvent {
    event: string
    properties: Record<string, unknown>
    timestamp: string
}

interface BatchEvent {
    event: string
    timestamp: string
    distinct_id: string
    properties: Record<string, unknown>
}

interface Sender {
    distinctId: string
    installId: string
    identified: boolean
    properties: Record<string, unknown>
}

export interface SentEvent {
    sent: boolean
    identified: boolean
}

interface Identity {
    distinctId?: string
    organization?: string
    project?: string
}

const CachedIdentitySchema = z.object({
    checkedAt: z.number(),
    distinctId: z.string().optional(),
    organization: z.string().optional(),
    project: z.string().optional(),
})

type CachedIdentity = z.output<typeof CachedIdentitySchema>

// hog writes this file itself, so a cache it can't read is broken and hog starts a new one.
const IdentityCacheSchema = z.record(z.string(), CachedIdentitySchema)

// Only PostHog Cloud users exist in the project telemetry goes to.
function isCloudHost(host: string): boolean {
    const { hostname } = new URL(host)
    return hostname === 'posthog.com' || hostname.endsWith('.posthog.com')
}

// A field hog can't read, such as a null organization, reads as missing, so the event loses only
// that field.
const Text = z.string().min(1).optional().catch(undefined)
const IdentityUser = z.object({ distinct_id: Text, organization: z.object({ id: Text }).optional().catch(undefined) })
const IdentityProject = z.object({ organization: Text, uuid: Text })

// Usage events for the PostHog team. They belong to the PostHog Cloud user whose key hog uses, and
// to a random install ID otherwise. Events carry no argument or option values and no error messages,
// only names, counts and error codes.
export class Telemetry {
    private readonly queue: QueuedEvent[] = []
    private enabled: boolean
    private loggedIn: AccessKey | undefined
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

    // The run logged in as `key`, so its events belong to that user, and so do the install ID's
    // earlier events, such as the ones a person sent before they had an account.
    loggedInAs(key: AccessKey): void {
        this.loggedIn = key
    }

    async flush(debug = false): Promise<void> {
        if (!this.enabled || this.queue.length === 0) {
            return
        }

        const sender = await this.sender()
        if (this.loggedIn && sender.identified) {
            this.queue.unshift({
                event: '$identify',
                properties: { $anon_distinct_id: sender.installId },
                timestamp: new Date(this.runtime.now()).toISOString(),
            })
        }

        const batch = this.queue.splice(0).map(({ event, properties, timestamp }) => ({
            event,
            timestamp,
            distinct_id: sender.distinctId,
            properties: { ...sender.properties, ...properties },
        }))
        await this.post(batch, debug)
    }

    // Sends one event a person asked hog to send, such as feedback, at once and outside the usage
    // queue. Unless it belongs to the person's PostHog user, it goes out under an ID of its own, with
    // no install ID or invocation ID: an earlier login can have linked the install ID to that user,
    // and this run's usage event pairs the invocation ID with the install ID.
    async send(event: string, properties: Record<string, unknown>, debug = false): Promise<SentEvent> {
        if (this.runtime.telemetryToken === undefined) {
            return { sent: false, identified: false }
        }

        const known = this.enabled ? await this.sender() : undefined
        const sender: Sender = known?.identified
            ? known
            : {
                  distinctId: randomUUID(),
                  installId: '',
                  identified: false,
                  properties: { ...this.commonProperties(), invocation_id: undefined, $process_person_profile: false },
              }
        const sent = await this.post(
            [
                {
                    event,
                    timestamp: new Date(this.runtime.now()).toISOString(),
                    distinct_id: sender.distinctId,
                    properties: { ...sender.properties, ...properties },
                },
            ],
            debug
        )
        return { sent, identified: sent && sender.identified }
    }

    private async sender(): Promise<Sender> {
        const key = this.loggedIn ?? (await this.credentials?.().catch(() => undefined))?.key
        const identity = key ? await this.identity(key) : undefined
        const installId = await this.installId()
        const workload = key?.workload && isCloudHost(key.host) ? key.workload : undefined
        // Each CI run is a new machine, and the hash keeps the repository ID out of the event.
        const workloadId =
            workload &&
            `workload_${createHash('sha256').update(`${key?.host}\n${workload.provider}\n${workload.subject}`).digest('hex').slice(0, 32)}`
        const groups = Object.fromEntries(
            Object.entries({
                organization: identity?.organization ?? workload?.organization,
                project: identity?.project,
            }).filter(([, key]) => key !== undefined)
        )

        return {
            distinctId: identity?.distinctId ?? workloadId ?? installId,
            installId,
            identified: identity?.distinctId !== undefined,
            properties: {
                ...this.commonProperties(),
                install_id: installId,
                // A self-hosted project ID means nothing in PostHog Cloud and would tie the install to that instance.
                env_id: key && isCloudHost(key.host) ? key.projectId : null,
                credential_type: key?.status().kind ?? null,
                ...(workload ? { workload_provider: workload.provider } : {}),
                ...(identity?.distinctId ? {} : { $process_person_profile: false }),
                ...(Object.keys(groups).length > 0 ? { $groups: groups } : {}),
            },
        }
    }

    private async post(batch: BatchEvent[], debug: boolean): Promise<boolean> {
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
            return response.ok
        } catch (error) {
            if (debug) {
                this.runtime.writeStderr(
                    `[debug] telemetry: not sent: ${error instanceof Error ? error.message : error}\n`
                )
            }
            return false
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
            is_ci: isRunningInCI(env),
            ci_provider: ci.provider,
            ci_runner: ci.runner,
            is_terminal: this.runtime.stdoutIsTTY,
            agent: this.mode.agent ?? null,
            output_format: this.mode.format,
        }
    }

    // Looks the user up once per key and keeps the answer for 30 days, or a day when PostHog had
    // none, so most runs send no extra request. A key without the scopes stays anonymous.
    private async identity(key: AccessKey): Promise<Identity | undefined> {
        if (!isCloudHost(key.host) || !key.identifiesPerson) {
            return undefined
        }
        let path: string
        try {
            path = posthogFile(this.runtime, IDENTITY_FILE)
        } catch {
            return undefined
        }
        const cacheKey = createHash('sha256').update(`${key.host}\n${key.projectId}\n${key.loginKey}`).digest('hex')
        let cache: Record<string, CachedIdentity> = {}
        try {
            cache = parseJsonOrUndefined(await this.runtime.readFile(path), IdentityCacheSchema) ?? {}
        } catch {
            // No cache yet.
        }
        const cached = cache[cacheKey]
        const now = this.runtime.now()
        if (cached && now - cached.checkedAt < (cached.distinctId ? 30 : 1) * DAY_MS) {
            return cached
        }
        const identity = await this.lookup(key)
        // Entries old enough to be looked up again anyway are dropped, so logins that ended don't pile up.
        cache = Object.fromEntries(Object.entries(cache).filter(([, entry]) => now - entry.checkedAt < 30 * DAY_MS))
        cache[cacheKey] = { ...identity, checkedAt: now }
        try {
            await this.runtime.writePrivateFile(path, JSON.stringify(cache))
        } catch {
            // Unwritable home: the next run looks it up again.
        }
        return identity
    }

    private async lookup(key: AccessKey): Promise<Identity> {
        const get = async <T>(path: string, schema: Schema<T>): Promise<T | undefined> => {
            try {
                const response = await this.runtime.fetch(new URL(path, key.host), {
                    headers: { Authorization: `Bearer ${key.token}` },
                    signal: AbortSignal.timeout(LOOKUP_TIMEOUT_MS),
                })
                return response.ok ? parseJsonOrUndefined(await response.text(), schema) : undefined
            } catch {
                return undefined
            }
        }
        const [user, project] = await Promise.all([
            get('/api/users/@me/', IdentityUser),
            get(`/api/projects/${key.projectId}/`, IdentityProject),
        ])
        return {
            distinctId: user?.distinct_id,
            organization: project?.organization ?? user?.organization?.id,
            project: project?.uuid,
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
