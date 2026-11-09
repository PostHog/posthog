import type { ApiToolLibrary } from '@posthog/mcp/src/cli/library-types'

import { PostHogApi } from '@/posthog/api'
import { resolveCredentials, type Credentials } from '@/posthog/credentials'
import { KeySession } from '@/posthog/key-session'
import { canStepUp } from '@/posthog/scope-challenge'

import type { Mode } from './agent'
import type { CommandTree } from './command'
import { loadConfig, type LoadedConfig } from './config'
import type { GlobalOptions } from './globals'
import type { Prompts } from './prompts'
import type { Runtime } from './runtime'
import { Telemetry } from './telemetry'

// What a command's `run` gets besides its own arguments and options. It has no output on
// purpose: `run` returns data, and the command's `human` and `agent` views print it.
export class Context {
    private api?: PostHogApi
    private credentialsRequest?: Promise<Credentials>
    private keySession?: Promise<KeySession>
    private loaded?: Promise<LoadedConfig | undefined>
    private tools?: Promise<ApiToolLibrary>
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

    // The nearest posthog.json, or undefined when there is none. Throws `invalid_config` when it
    // doesn't match the schema.
    config(): Promise<LoadedConfig | undefined> {
        this.loaded ??= loadConfig(this.runtime)
        return this.loaded
    }

    apiTools(): Promise<ApiToolLibrary> {
        this.tools ??= this.runtime.loadApiTools()
        return this.tools
    }

    // Throws `not_authenticated` when there are none.
    credentials(): Promise<Credentials> {
        this.credentialsRequest ??= this.config().then((loaded) =>
            resolveCredentials(this.runtime, {
                ...this.globals,
                configHost: loaded?.config.host,
                configProjectId: loaded?.config.projectId?.toString(),
            })
        )
        return this.credentialsRequest
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
