import type { ApiToolLibrary, SkillsLibrary } from '@posthog/mcp/src/cli/library-types'

import { PostHogApi } from '@/posthog/api'
import { resolveCatalog, type ResolvedCatalog } from '@/posthog/api-catalog'
import {
    loginQuery,
    posthogPath,
    resolveCredentials,
    type CredentialOptions,
    type Credentials,
} from '@/posthog/credentials'
import { parseHost, REGIONS, type Host } from '@/posthog/host'
import { parseProjectId } from '@/posthog/ids'
import { KeySession } from '@/posthog/key-session'
import type { LoginQuery } from '@/posthog/login/choose'
import { canStepUp } from '@/posthog/scope-challenge'
import { fallbackHost, readSettings } from '@/posthog/settings'

import type { Mode } from './agent'
import type { CommandTree } from './command'
import { loadConfig, type LoadedConfig } from './config'
import type { GlobalOptions } from './globals'
import type { Prompts } from './prompts'
import type { Runtime } from './runtime'
import { SKILL_COMMANDS } from './skill-commands'
import { Telemetry } from './telemetry'

// What a command's `run` gets besides its own arguments and options. It has no output on
// purpose: `run` returns data, and the command's `human` and `agent` views print it.
export class Context {
    private api?: PostHogApi
    private credentialsRequest?: Promise<Credentials>
    private keySession?: Promise<KeySession>
    private loaded?: Promise<LoadedConfig | undefined>
    private tools?: Promise<ApiToolLibrary>
    private skillsLibrary?: Promise<SkillsLibrary>
    private stepUpRunning?: Promise<boolean>

    constructor(
        readonly runtime: Runtime,
        readonly globals: GlobalOptions,
        readonly mode: Mode,
        readonly tree: CommandTree,
        loaded?: Promise<LoadedConfig | undefined>,
        readonly telemetry: Telemetry = new Telemetry(runtime, mode, false)
    ) {
        this.loaded = loaded
    }

    // Undefined unless a person is at the terminal, so a command can ask questions only when
    // someone can answer them. Agents, pipes and `-o json` never get prompts.
    get prompts(): Prompts | undefined {
        const person = this.mode.format === 'text' && this.mode.agent === undefined
        return person && this.runtime.stdinIsTTY && this.runtime.stdoutIsTTY ? this.runtime.prompts : undefined
    }

    // The PostHog API client. Credentials resolve on first use, so commands that never call
    // the API work without them.
    async posthog(): Promise<PostHogApi> {
        this.api ??= new PostHogApi(await this.session(), this.runtime.fetch, (scopes) => this.stepUp(scopes))
        return this.api
    }

    // Called once a command knows what it will write, so a step-up comes before the first write.
    async ensureScopes(scopes: readonly string[], action?: string): Promise<void> {
        if (!canStepUp(await this.credentials().catch(() => undefined))) {
            return
        }
        const { ensureScopes } = await import('@/posthog/login/step-up')
        await ensureScopes(this, scopes, action)
    }

    // Requests sent at once step up one at a time, and a failed step-up, such as a cancel, fails the rest.
    stepUp(scopes: readonly string[]): Promise<boolean> {
        const run = (this.stepUpRunning ?? Promise.resolve(false)).then(async () => {
            const { promptStepUp } = await import('@/posthog/login/step-up')
            return promptStepUp(this, scopes)
        })
        this.stepUpRunning = run
        return run
    }

    // Forgets posthog.json and the credentials, after the command wrote either one, so the next call
    // reads them again. The telemetry for this run then belongs to the new login.
    reload(): void {
        this.loaded = undefined
        this.credentialsRequest = undefined
        this.keySession = undefined
        this.api = undefined
    }

    // The nearest posthog.json, or undefined when there is none. Throws `invalid_config` when it
    // doesn't match the schema.
    config(): Promise<LoadedConfig | undefined> {
        this.loaded ??= loadConfig(this.runtime)
        return this.loaded
    }

    apiTools({ refresh = false }: { refresh?: boolean } = {}): Promise<ApiToolLibrary> {
        if (refresh || !this.tools) {
            this.tools = this.loadApiTools(refresh)
        }
        return this.tools
    }

    catalog: ResolvedCatalog | undefined

    private async loadApiTools(refresh: boolean): Promise<ApiToolLibrary> {
        const resolved = await resolveCatalog(this.runtime, { host: (await this.apiHost()) ?? REGIONS.us, refresh })
        this.catalog = resolved
        const library = await this.runtime.loadApiTools(resolved.catalog ? { catalog: resolved.catalog } : {})

        if (this.globals.debug) {
            const status = library.catalog()
            const source =
                status.source === 'downloaded'
                    ? `${status.tools} tools from the ${resolved.origin === 'network' ? 'downloaded' : 'saved'} catalog`
                    : `the tools built into hog, because ${status.rejected ?? resolved.reason}`
            this.runtime.writeStderr(`[debug] api catalog: ${source}\n`)
            if (resolved.retryAfter !== null) {
                const when = new Date(resolved.retryAfter).toISOString()
                this.runtime.writeStderr(
                    resolved.downloadSkipped
                        ? `[debug] api catalog: skipped the download until ${when}, because the last one failed\n`
                        : `[debug] api catalog: the download failed, so hog tries again after ${when}\n`
                )
            }
            for (const dropped of status.dropped) {
                const action = dropped.builtIn ? 'kept the built-in' : 'left out'
                this.runtime.writeStderr(`[debug] api catalog: ${action} ${dropped.name}, because ${dropped.reason}\n`)
            }
        }
        return library
    }

    // The host API calls go to, found without reading the keychain, since browsing tools needs no login.
    private async apiHost(): Promise<Host | undefined> {
        const requested = await this.requestedCredentials?.catch(() => undefined)
        if (requested) {
            return requested.key.host
        }
        // A key in the environment or --dotenv-file carries its own host, and reading it needs no keychain.
        const fromEnv = await this.credentialOptions()
            .then((options) => resolveCredentials(this.runtime, { ...options, envOnly: true }))
            .catch(() => undefined)
        if (fromEnv) {
            return fromEnv.key.host
        }
        const configHost = (await this.config().catch(() => undefined))?.config.host
        const raw = this.globals.host ?? configHost
        if (raw !== undefined) {
            try {
                return parseHost(raw)
            } catch {
                return undefined
            }
        }
        try {
            return fallbackHost(await readSettings(this.runtime))
        } catch {
            return undefined
        }
    }

    // The PostHog agent skills, saved in ~/.posthog/skills for when a download fails. Without a home
    // folder, the skills still download and nothing is saved.
    skills(): Promise<SkillsLibrary> {
        this.skillsLibrary ??= this.runtime.loadSkills({
            cacheDir: posthogPath(this.runtime, 'skills'),
            commands: SKILL_COMMANDS,
            // The downloads go to GitHub, not PostHog, so --rate-limit doesn't count them.
            fetch: (url, init) => this.runtime.fetch(url, { ...init, skipRateLimit: true }),
        })
        return this.skillsLibrary
    }

    private async credentialOptions(): Promise<CredentialOptions> {
        const loaded = await this.config()
        const projectId = loaded?.config.projectId

        return {
            ...this.globals,
            configPath: loaded?.path,
            configHost: loaded?.config.host,
            configProjectId: projectId === undefined ? undefined : parseProjectId(projectId),
        }
    }

    // Throws `not_authenticated` when there are none.
    credentials(): Promise<Credentials> {
        this.credentialsRequest ??= this.credentialOptions().then((options) =>
            resolveCredentials(this.runtime, options)
        )
        return this.credentialsRequest
    }

    async loginQuery(): Promise<LoginQuery> {
        return loginQuery(this.runtime, await this.credentialOptions())
    }

    // The key every client of this command sends, so they share its renewals.
    session(): Promise<KeySession> {
        this.keySession ??= this.credentials().then(
            (credentials) => new KeySession(this.runtime, credentials.key, credentials.storage)
        )
        return this.keySession
    }

    // The credentials the command already asked for, so telemetry doesn't read the keychain a second time.
    get requestedCredentials(): Promise<Credentials> | undefined {
        return this.credentialsRequest
    }
}
