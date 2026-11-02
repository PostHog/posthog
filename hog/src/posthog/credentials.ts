import { join } from 'node:path'

import { EXIT_USAGE, HogError } from '@/core/errors'
import type { Env, Runtime } from '@/core/runtime'

import { FileStore } from './credential-store'
import { readLogin } from './logins'
import { freshOAuthCredential } from './oauth'
import { readSettings } from './settings'

// posthog-cli falls back to this host when neither --host nor the credentials name one.
export const DEFAULT_HOST = 'https://us.i.posthog.com'

export interface Credentials {
    // A personal API key or an OAuth access token, sent as a bearer token.
    token: string
    projectId: string
    host: string
    // Stays the same for the whole login, unlike OAuth tokens, which change on each renewal.
    loginKey?: string
}

// `store` is what `hog auth login` saved. `posthog-cli-file` is posthog-cli's credentials file, which
// hog reads but never writes.
export type CredentialSource = 'env' | 'dotenv-file' | 'store' | 'posthog-cli-file'

export type ResolvedCredentials = Credentials & {
    kind: 'personal_api_key' | 'oauth'
    source: CredentialSource
    // Set when the source is the store.
    store?: 'keychain' | 'file'
    // The file the credentials came from, when they came from one.
    path?: string
    scopes?: string[]
    expiresAt?: number
}

interface RawCredentials {
    kind: 'personal_api_key' | 'oauth'
    token: string
    projectId: string
    host: string | undefined
}

export const PERSONAL_API_KEY_ENV_VAR = 'HOG_PERSONAL_API_KEY'

// The host only counts when it comes from the same source as the key, so a stray host cannot
// redirect a key from somewhere else.
function fromLookup(lookup: (name: string) => string | undefined): RawCredentials | undefined {
    const apiKey = lookup(PERSONAL_API_KEY_ENV_VAR)
    const projectId = lookup('HOG_PROJECT_ID')
    if (!apiKey || !projectId) {
        return undefined
    }
    return { kind: 'personal_api_key', token: apiKey, projectId, host: lookup('HOG_HOST') || undefined }
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
    if (env.HOG_HOME) {
        return env.HOG_HOME
    }
    return homeDir === undefined ? undefined : join(homeDir, '.posthog')
}

export function posthogFile(runtime: Runtime, name: string): string {
    const home = posthogHomeDir(runtime.env, runtime.homeDir())
    if (home === undefined) {
        throw new HogError(
            'no_home_directory',
            "hog couldn't find your home folder to store credentials in.",
            'Set HOG_HOME to the folder to use.'
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

function sameOrigin(a: string, b: string): boolean {
    return URL.canParse(a) && URL.canParse(b) && new URL(a).origin === new URL(b).origin
}

export function checkHost(host: string): string | undefined {
    return URL.canParse(host) ? undefined : `The host must be a valid URL, but it is "${host}".`
}

function validate(raw: RawCredentials, host: string): Credentials {
    const keyError = raw.kind === 'personal_api_key' ? checkApiKey(raw.token) : undefined
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
    return { token: raw.token, projectId: raw.projectId, host }
}

export function posthogCliCredentialsPath(runtime: Runtime): string {
    return posthogFile(runtime, 'credentials.json')
}

// Every credential source, in order: HOG_PERSONAL_API_KEY in the environment, then in --dotenv-file,
// then what `hog auth login` stored, then posthog-cli's credentials file. The global host overrides
// whichever host the source carried, and picks which stored login to use. posthog.json comes from
// the repository, so its host never redirects a key: it can pick a stored login for that host, and
// otherwise only stops the command when the key belongs to another host.
export async function resolveCredentials(
    runtime: Runtime,
    // `includeStore: false` leaves out what `hog auth login` stored, for callers that must never
    // open the keychain or renew a token, like telemetry for a command that needed no credentials.
    options: { host?: string; dotenvFile?: string; configHost?: string; includeStore?: boolean }
): Promise<ResolvedCredentials> {
    const checkConfigHost = (host: string): void => {
        const { configHost } = options
        if (options.host === undefined && configHost !== undefined && !sameOrigin(configHost, host)) {
            throw new HogError(
                'host_mismatch',
                `posthog.json sets the host to ${configHost}, but your credentials are for ${host}.`,
                `Pass --host ${configHost} or set HOG_HOST to send your credentials there, or log in to that host with \`hog auth login --host ${configHost}\`.`,
                EXIT_USAGE
            )
        }
    }
    const withHost = (
        raw: RawCredentials,
        source: CredentialSource,
        extra: Pick<ResolvedCredentials, 'store' | 'path' | 'scopes' | 'expiresAt' | 'loginKey'> = {}
    ): ResolvedCredentials => {
        const host = options.host ?? raw.host ?? DEFAULT_HOST
        checkConfigHost(host)
        return { ...validate(raw, host), kind: raw.kind, source, ...extra }
    }

    const fromEnv = fromLookup((name) => runtime.env[name] || undefined)
    if (fromEnv) {
        return withHost(fromEnv, 'env')
    }

    const dotenvFile = options.dotenvFile
    if (dotenvFile) {
        const contents = await readDotenv(runtime, dotenvFile)
        if (contents !== undefined) {
            const values = parseDotenv(contents, dotenvFile)
            const fromFile = fromLookup((name) => values.get(name) || undefined)
            if (!fromFile) {
                throw new HogError(
                    'not_authenticated',
                    `hog couldn't find HOG_PERSONAL_API_KEY and HOG_PROJECT_ID in the environment or in ${dotenvFile}.`,
                    'Add both variables to the file, or remove --dotenv-file.'
                )
            }
            return withHost(fromFile, 'dotenv-file', { path: dotenvFile })
        }
    }

    if (options.includeStore !== false) {
        const settings = await readSettings(runtime)
        const hosts = options.host !== undefined ? [options.host] : [options.configHost, settings.host]
        for (const host of new Set(hosts)) {
            const login = host === undefined ? undefined : await readLogin(runtime, settings, host)
            if (!login) {
                continue
            }
            const { credential: stored, store } = login
            // Before a renewal, so hog never renews a token it then refuses to send.
            checkConfigHost(stored.host)
            const credential = stored.type === 'oauth' ? await freshOAuthCredential(runtime, store, stored) : stored
            const oauth = credential.type === 'oauth'
            return withHost(
                {
                    kind: credential.type,
                    token: oauth ? credential.accessToken : credential.apiKey,
                    projectId: credential.projectId,
                    host: credential.host,
                },
                'store',
                {
                    store: store.kind,
                    path: store instanceof FileStore ? store.path : undefined,
                    ...(oauth
                        ? {
                              scopes: credential.scopes,
                              expiresAt: credential.expiresAt,
                              loginKey: credential.loginId,
                          }
                        : {}),
                }
            )
        }
    }

    const home = posthogHomeDir(runtime.env, runtime.homeDir())
    if (home !== undefined) {
        const path = join(home, 'credentials.json')
        let stored: { token?: unknown; env_id?: unknown; host?: unknown } | undefined
        try {
            stored = JSON.parse(await runtime.readFile(path))
        } catch {
            stored = undefined
        }
        if (stored && typeof stored.token === 'string' && stored.env_id !== undefined) {
            const raw: RawCredentials = {
                kind: 'personal_api_key',
                token: stored.token,
                projectId: String(stored.env_id),
                host: typeof stored.host === 'string' ? stored.host : undefined,
            }
            return withHost(raw, 'posthog-cli-file', { path })
        }
    }

    throw new HogError(
        'not_authenticated',
        "hog couldn't find PostHog credentials.",
        'Run `hog auth login`, or set HOG_PERSONAL_API_KEY and HOG_PROJECT_ID.'
    )
}
