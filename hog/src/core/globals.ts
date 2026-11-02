import type { OptionSpec, OptionValues } from './command'
import type { PostHogConfig } from './config'
import { EXIT_USAGE, HogError } from './errors'
import type { Env, Runtime, RuntimeFetch } from './runtime'
import { kebabCase } from './text'

// Options every command takes. Each one also reads the env vars in `env`, in order, and some read
// the posthog.json key at the `config` path. A flag beats an env var, which beats posthog.json.
export const GLOBAL_OPTIONS = {
    host: {
        type: 'string',
        placeholder: 'url',
        env: ['HOG_HOST'],
        description: 'The PostHog host to use instead of the one in your credentials',
    },
    dotenvFile: {
        type: 'string',
        placeholder: 'path',
        env: ['HOG_DOTENV_FILE'],
        description: 'Read HOG_API_KEY, HOG_PROJECT_ID and HOG_HOST from this file when the environment has none',
    },
    output: {
        type: 'string',
        short: 'o',
        placeholder: 'format',
        choices: ['text', 'json'],
        env: ['HOG_OUTPUT'],
        description: 'Output format, json by default for agents and pipes',
    },
    raw: {
        type: 'boolean',
        env: ['HOG_RAW'],
        description: 'Print the full result as JSON, without the formatting for people or agents',
    },
    debug: {
        type: 'boolean',
        env: ['HOG_DEBUG'],
        description: 'Print each HTTP request hog sends, with its status and duration, to stderr',
    },
    noFail: {
        type: 'boolean',
        env: ['HOG_NO_FAIL'],
        config: 'cli.noFail',
        description: 'Exit with code 0 when the command fails or reports a problem, for builds that must not break',
    },
    skipSslVerification: {
        type: 'boolean',
        env: ['HOG_SKIP_SSL_VERIFICATION'],
        description: 'Accept any TLS certificate, for a self-hosted PostHog with a self-signed one',
    },
    noTelemetry: {
        type: 'boolean',
        env: ['HOG_NO_TELEMETRY', 'DO_NOT_TRACK'],
        config: 'cli.telemetry',
        negate: true,
        lenient: true,
        description: 'Send no anonymous usage data to PostHog',
    },
    rateLimit: {
        type: 'string',
        placeholder: 'requests',
        env: ['HOG_RATE_LIMIT'],
        config: 'cli.rateLimit',
        description: 'The most requests hog sends per minute',
    },
} as const satisfies Record<string, OptionSpec>

export type GlobalOptions = OptionValues<typeof GLOBAL_OPTIONS>

export const DRY_RUN_ENV = ['HOG_DRY_RUN'] as const

const TRUE_VALUES = new Set(['1', 'true', 'yes', 'on'])
const FALSE_VALUES = new Set(['0', 'false', 'no', 'off', ''])

export function envFlag(env: Env, names: readonly string[]): boolean | undefined {
    for (const name of names) {
        const value = env[name]
        if (value === undefined) {
            continue
        }
        const normalized = value.trim().toLowerCase()
        if (TRUE_VALUES.has(normalized)) {
            return true
        }
        if (FALSE_VALUES.has(normalized)) {
            return false
        }
        throw new HogError(
            'invalid_setting',
            `${name} must be true or false, but it is "${value}".`,
            `Set ${name} to 1 or 0.`,
            EXIT_USAGE
        )
    }
    return undefined
}

// For opt-outs shared with other tools, like DO_NOT_TRACK: any value but an explicit "no" opts out,
// and an unknown value never breaks a command.
export function optOutFlag(env: Env, names: readonly string[]): boolean | undefined {
    const set = names.map((name) => env[name]?.trim().toLowerCase()).filter((value) => value !== undefined)
    if (set.length === 0) {
        return undefined
    }
    return set.some((value) => !FALSE_VALUES.has(value))
}

function envValue(env: Env, names: readonly string[]): { name: string; value: string } | undefined {
    for (const name of names) {
        const value = env[name]
        if (value) {
            return { name, value }
        }
    }
    return undefined
}

function configValue(config: PostHogConfig, path: string): unknown {
    return path
        .split('.')
        .reduce<unknown>((parent, key) => (parent as Record<string, unknown> | undefined)?.[key], config)
}

export function resolveGlobals(
    flags: Readonly<Record<string, unknown>>,
    env: Env,
    config: PostHogConfig = {}
): GlobalOptions {
    const resolved: Record<string, unknown> = {}
    for (const [name, spec] of Object.entries(GLOBAL_OPTIONS) as [string, OptionSpec][]) {
        const envNames = spec.env ?? []
        let value: unknown = flags[name]
        let source = `--${kebabCase(name)}`
        if (value === undefined && spec.type === 'boolean' && spec.lenient) {
            value = optOutFlag(env, envNames)
        } else if (value === undefined && spec.type === 'boolean') {
            value = envFlag(env, envNames)
            source = envNames.find((envName) => env[envName] !== undefined) ?? source
        } else if (value === undefined) {
            const fromEnv = envValue(env, envNames)
            value = fromEnv?.value
            source = fromEnv?.name ?? source
        }
        const configured = spec.config === undefined ? undefined : configValue(config, spec.config)
        if (value === undefined && configured !== undefined) {
            value = spec.type === 'string' ? String(configured) : spec.negate ? !configured : configured
            source = `${spec.config} in posthog.json`
        }
        if (spec.type === 'string' && spec.choices && value !== undefined && !spec.choices.includes(String(value))) {
            throw new HogError(
                'invalid_setting',
                `${source} must be one of ${spec.choices.join(', ')}, but it is "${String(value)}".`,
                undefined,
                EXIT_USAGE
            )
        }
        resolved[name] = value
    }
    const globals = resolved as GlobalOptions
    if (globals.rateLimit !== undefined && !/^[1-9]\d*$/.test(globals.rateLimit)) {
        throw new HogError(
            'invalid_setting',
            `The rate limit must be a whole number of requests per minute, but it is "${globals.rateLimit}".`,
            undefined,
            EXIT_USAGE
        )
    }
    return globals
}

const WINDOW_MS = 60_000

export function networkRuntime(runtime: Runtime, globals: GlobalOptions): Runtime {
    if (globals.skipSslVerification) {
        runtime.skipTlsVerification()
    }
    const limit = globals.rateLimit === undefined ? undefined : Number(globals.rateLimit)
    if (limit === undefined && !globals.debug) {
        return runtime
    }
    const started: number[] = []
    let queue = Promise.resolve()
    const waitTurn = (): Promise<void> => {
        const turn = queue.then(async () => {
            if (limit === undefined) {
                return
            }
            while (started.length > 0 && runtime.now() - started[0]! >= WINDOW_MS) {
                started.shift()
            }
            if (started.length >= limit) {
                await runtime.sleep(WINDOW_MS - (runtime.now() - started[0]!))
                started.shift()
            }
            started.push(runtime.now())
        })
        queue = turn
        return turn
    }
    const fetch: RuntimeFetch = async (input, init) => {
        if (!init?.skipRateLimit) {
            await waitTurn()
        }
        if (!globals.debug) {
            return runtime.fetch(input, init)
        }
        const url = new URL(input instanceof Request ? input.url : String(input))
        // The query string can carry a signed upload URL's credentials, so only the path prints.
        const label = `${init?.method ?? 'GET'} ${url.origin}${url.pathname}`
        const begin = runtime.now()
        try {
            const response = await runtime.fetch(input, init)
            runtime.writeStderr(`[debug] ${label} ${response.status} ${runtime.now() - begin}ms\n`)
            return response
        } catch (error) {
            runtime.writeStderr(`[debug] ${label} failed: ${error instanceof Error ? error.message : error}\n`)
            throw error
        }
    }
    return { ...runtime, fetch }
}
