import { join } from 'node:path'

import { HogError } from '@/core/errors'
import type { Env, Runtime } from '@/core/runtime'

// posthog-cli falls back to this host when neither --host nor the credentials name one.
export const DEFAULT_HOST = 'https://us.i.posthog.com'

export interface Credentials {
    apiKey: string
    projectId: string
    host: string
}

export type CredentialSource = 'env' | 'dotenv-file' | 'credentials-file'

export type ResolvedCredentials = Credentials & { source: CredentialSource }

interface RawCredentials {
    apiKey: string
    projectId: string
    host: string | undefined
}

export const API_KEY_ENV_VARS = ['POSTHOG_CLI_API_KEY', 'POSTHOG_CLI_TOKEN'] as const

// Same variables and aliases as posthog-cli. The host only counts when it comes from the
// same source as the key, so a stray host cannot redirect a key from somewhere else.
function fromLookup(lookup: (name: string) => string | undefined): RawCredentials | undefined {
    const apiKey = lookup(API_KEY_ENV_VARS[0]) ?? lookup(API_KEY_ENV_VARS[1])
    const projectId = lookup('POSTHOG_CLI_PROJECT_ID') ?? lookup('POSTHOG_CLI_ENV_ID')
    if (!apiKey || !projectId) {
        return undefined
    }
    return { apiKey, projectId, host: lookup('POSTHOG_CLI_HOST') || undefined }
}

function parseDotenv(contents: string, path: string): Map<string, string> {
    const values = new Map<string, string>()
    contents.split(/\r?\n/).forEach((raw, index) => {
        const line = raw.trim()
        if (!line || line.startsWith('#')) {
            return
        }
        const separator = line.indexOf('=')
        const key = separator === -1 ? '' : line.slice(0, separator).trim()
        if (!key) {
            throw new HogError(
                'invalid_dotenv_file',
                `Line ${index + 1} of ${path} is not KEY=VALUE.`,
                'Fix the line, or remove --dotenv-file.'
            )
        }
        let value = line.slice(separator + 1).trim()
        const quote = value[0]
        if (value.length >= 2 && (quote === '"' || quote === "'") && value.at(-1) === quote) {
            value = value.slice(1, -1)
        }
        values.set(key, value)
    })
    return values
}

// A missing file only warns, as in posthog-cli, so a shared build script still works on a machine
// that logged in instead. Any other read failure stops the command.
async function readDotenv(runtime: Runtime, path: string): Promise<string | undefined> {
    try {
        return await runtime.readFile(path)
    } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'ENOENT') {
            throw new HogError(
                'invalid_dotenv_file',
                `hog couldn't read ${path}: ${error instanceof Error ? error.message : String(error)}`,
                'Check that the file is readable, or remove --dotenv-file.'
            )
        }
        runtime.writeStderr(`Warning: ${path} doesn't exist, so hog uses your other credentials.\n`)
        return undefined
    }
}

function posthogHomeDir(env: Env, homeDir: string | undefined): string | undefined {
    if (env.POSTHOG_HOME) {
        return env.POSTHOG_HOME
    }
    return homeDir === undefined ? undefined : join(homeDir, '.posthog')
}

export function posthogFile(runtime: Runtime, name: string): string {
    const home = posthogHomeDir(runtime.env, runtime.homeDir())
    if (home === undefined) {
        throw new HogError(
            'no_home_directory',
            "hog couldn't find your home folder to store credentials in.",
            'Set POSTHOG_HOME to the folder to use.'
        )
    }
    return join(home, name)
}

export function checkApiKey(apiKey: string): string | undefined {
    return apiKey.startsWith('phx_') ? undefined : "The personal API key doesn't look right: it must start with 'phx_'."
}

export function checkProjectId(projectId: string): string | undefined {
    return /^\d+$/.test(projectId) ? undefined : `The project ID must be a number, but it is "${projectId}".`
}

export function checkHost(host: string): string | undefined {
    return URL.canParse(host) ? undefined : `The host must be a valid URL, but it is "${host}".`
}

function validate(raw: RawCredentials, host: string): Credentials {
    const keyError = checkApiKey(raw.apiKey)
    if (keyError) {
        throw new HogError(
            'invalid_credentials',
            keyError,
            'Create a personal API key in PostHog under Settings > Personal API keys.'
        )
    }
    const projectError = checkProjectId(raw.projectId)
    if (projectError) {
        throw new HogError(
            'invalid_credentials',
            projectError,
            'Use the number in your project URL, like the 2 in https://us.posthog.com/project/2.'
        )
    }
    const hostError = checkHost(host)
    if (hostError) {
        throw new HogError('invalid_credentials', hostError)
    }
    return { apiKey: raw.apiKey, projectId: raw.projectId, host }
}

// Same file and fields as posthog-cli, so either CLI can use a login made by the other.
export async function saveCredentials(runtime: Runtime, credentials: Credentials): Promise<string> {
    const path = posthogFile(runtime, 'credentials.json')
    const stored = { host: credentials.host, token: credentials.apiKey, env_id: credentials.projectId }
    await runtime.writePrivateFile(path, JSON.stringify(stored))
    return path
}

// Lookup order matches posthog-cli: process env, then --dotenv-file, then the credentials
// file `hog auth login` and `posthog-cli login` write. --host overrides whichever host the source carried.
export async function resolveCredentials(
    runtime: Runtime,
    options: { host?: string; dotenvFile?: string }
): Promise<ResolvedCredentials> {
    const withHost = (raw: RawCredentials, source: CredentialSource): ResolvedCredentials => ({
        ...validate(raw, options.host ?? raw.host ?? DEFAULT_HOST),
        source,
    })

    const fromEnv = fromLookup((name) => runtime.env[name] || undefined)
    if (fromEnv) {
        return withHost(fromEnv, 'env')
    }

    const dotenvFile = options.dotenvFile ?? (runtime.env.POSTHOG_CLI_DOTENV_FILE || undefined)
    if (dotenvFile) {
        const contents = await readDotenv(runtime, dotenvFile)
        if (contents !== undefined) {
            const values = parseDotenv(contents, dotenvFile)
            const fromFile = fromLookup((name) => values.get(name) || undefined)
            if (!fromFile) {
                throw new HogError(
                    'not_authenticated',
                    `hog couldn't find POSTHOG_CLI_API_KEY and POSTHOG_CLI_PROJECT_ID in the environment or in ${dotenvFile}.`,
                    'Add both variables to the file, or remove --dotenv-file.'
                )
            }
            return withHost(fromFile, 'dotenv-file')
        }
    }

    const home = posthogHomeDir(runtime.env, runtime.homeDir())
    if (home !== undefined) {
        let stored: { token?: unknown; env_id?: unknown; host?: unknown } | undefined
        try {
            stored = JSON.parse(await runtime.readFile(join(home, 'credentials.json')))
        } catch {
            stored = undefined
        }
        if (stored && typeof stored.token === 'string' && stored.env_id !== undefined) {
            const raw = {
                apiKey: stored.token,
                projectId: String(stored.env_id),
                host: typeof stored.host === 'string' ? stored.host : undefined,
            }
            return withHost(raw, 'credentials-file')
        }
    }

    throw new HogError(
        'not_authenticated',
        "hog couldn't find PostHog credentials.",
        'Run `hog auth login`, or set POSTHOG_CLI_API_KEY and POSTHOG_CLI_PROJECT_ID.'
    )
}
