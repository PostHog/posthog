import { PostHogApi } from '@/posthog/api'
import { resolveCredentials, type ResolvedCredentials } from '@/posthog/credentials'

import type { Mode } from './agent'
import type { CommandTree, OptionSpec, OptionValues } from './command'
import { loadConfig, type LoadedConfig } from './config'
import type { Prompts } from './prompts'
import type { Runtime } from './runtime'

export const GLOBAL_OPTIONS = {
    host: {
        type: 'string',
        placeholder: 'url',
        description: 'The PostHog host to use instead of the one in your credentials',
    },
    dotenvFile: {
        type: 'string',
        placeholder: 'path',
        description: 'Read POSTHOG_CLI_* credentials from this file when the environment has none',
    },
    output: {
        type: 'string',
        short: 'o',
        placeholder: 'format',
        choices: ['text', 'json'],
        description: 'Output format, json by default for agents and pipes',
    },
    raw: {
        type: 'boolean',
        description: 'Print the full result as JSON, without the formatting for people or agents',
    },
} as const satisfies Record<string, OptionSpec>

export type GlobalOptions = OptionValues<typeof GLOBAL_OPTIONS>

// What a command's `run` gets besides its own arguments and options. It has no output on
// purpose: `run` returns data, and the command's `human` and `agent` views print it.
export class Context {
    private api?: PostHogApi
    private resolved?: ResolvedCredentials
    private loaded?: Promise<LoadedConfig | undefined>

    constructor(
        readonly runtime: Runtime,
        readonly globals: GlobalOptions,
        readonly mode: Mode,
        readonly tree: CommandTree
    ) {}

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

    // Throws `not_authenticated` when there are none.
    async credentials(): Promise<ResolvedCredentials> {
        this.resolved ??= await resolveCredentials(this.runtime, this.globals)
        return this.resolved
    }
}
