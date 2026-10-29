import { PostHogApi } from '@/posthog/api'
import { resolveCredentials } from '@/posthog/credentials'

import type { Mode } from './agent'
import type { CommandTree, OptionSpec, OptionValues } from './command'
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

    constructor(
        readonly runtime: Runtime,
        readonly globals: GlobalOptions,
        readonly mode: Mode,
        readonly tree: CommandTree
    ) {}

    // The PostHog API client. Credentials resolve on first use, so commands that never call
    // the API work without them.
    async posthog(): Promise<PostHogApi> {
        if (!this.api) {
            const credentials = await resolveCredentials(this.runtime, this.globals)
            this.api = new PostHogApi(credentials, this.runtime.fetch)
        }
        return this.api
    }
}
