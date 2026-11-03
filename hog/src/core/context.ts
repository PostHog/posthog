import type { ApiToolLibrary } from '@posthog/mcp/src/cli/library-types'

import { PostHogApi } from '@/posthog/api'
import { resolveCredentials, type ResolvedCredentials } from '@/posthog/credentials'

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
    private resolved?: ResolvedCredentials
    private loaded?: Promise<LoadedConfig | undefined>
    private tools?: Promise<ApiToolLibrary>

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
        this.api ??= new PostHogApi(await this.credentials(), this.runtime.fetch)
        return this.api
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
    async credentials(): Promise<ResolvedCredentials> {
        this.resolved ??= await resolveCredentials(this.runtime, {
            ...this.globals,
            configHost: (await this.config())?.config.host,
        })
        return this.resolved
    }
}
