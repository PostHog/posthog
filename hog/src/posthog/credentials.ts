import { join } from 'node:path'

import { detectWorkloadProvider, type WorkloadProvider } from '@/ci/providers/registry'
import { EXIT_USAGE, HogError } from '@/core/errors'
import type { Env, Runtime } from '@/core/runtime'
import type { StoreChoice } from '@/posthog/credential-store/types'
import { chooseLogin, ProjectMismatch, type LoginChoice, type LoginQuery } from '@/posthog/login/choose'
import { loginStorage, readLogin } from '@/posthog/login/stored'

import { MemoryKeyStorage, PersonalAPIKey, type AccessKey, type AccessKeyStorage } from './access-key'
import { cloudRegion, hostKey, INGESTION_HOSTS, parseHost, REGIONS, type Host } from './host'
import { parseProjectId, type ProjectId } from './ids'
import { fallbackHost, readSettings } from './settings'
import { parsePersonalApiKey } from './tokens'
import { exchangeWorkloadToken } from './workload'

// posthog-cli falls back to this host when neither --host nor the credentials name one.
export const DEFAULT_HOST = INGESTION_HOSTS.us

export type Credentials = { key: AccessKey } & (
    | { source: 'env'; storage: null }
    | { source: 'dotenv-file'; path: string; storage: null }
    | { source: 'workload'; storage: AccessKeyStorage }
    // What `hog auth login` or `hog auth migrate` saved. `path` is the file that holds the secret,
    // and null for the keychain.
    | { source: 'store'; store: StoreChoice; path: string | null; storage: AccessKeyStorage; choice: LoginChoice }
)

export type CredentialSource = Credentials['source']

interface RawCredentials {
    apiKey: string
    projectId: ProjectId
    host: string | undefined
}

export const PERSONAL_API_KEY_ENV_VAR = 'HOG_PERSONAL_API_KEY'

export const PROJECT_SETTINGS_HINT = 'Put the project ID in posthog.json as "projectId", or set HOG_PROJECT_ID'
export const CI_CREDENTIALS_HINT =
    'Run `hog ci setup` on your machine, so the job trades its CI provider\'s OIDC token for a PostHog token and stores no key. Otherwise, set HOG_PERSONAL_API_KEY in the job, and put the project ID and the host in posthog.json as "projectId" and "host". The key never goes in posthog.json.'

// The host only counts when it comes from the same source as the key, so a stray host cannot
// redirect a key from somewhere else. The project ID only picks a project the key can already reach,
// so posthog.json can supply it.
function fromLookup(
    lookup: (name: string) => string | undefined,
    configProjectId: ProjectId | undefined
): RawCredentials | undefined {
    const apiKey = lookup(PERSONAL_API_KEY_ENV_VAR)
    const projectId = apiKey ? (lookupProjectId(lookup) ?? configProjectId) : undefined
    if (!apiKey || !projectId) {
        return undefined
    }

    return { apiKey, projectId, host: lookup('HOG_HOST') || undefined }
}

function lookupProjectId(lookup: (name: string) => string | undefined): ProjectId | undefined {
    const raw = lookup('HOG_PROJECT_ID')
    return raw
        ? parseProjectId(raw, { code: 'invalid_credentials', context: 'HOG_PROJECT_ID is not valid.' })
        : undefined
}

function envLookup(runtime: Runtime): (name: string) => string | undefined {
    return (name) => runtime.env[name] || undefined
}

function envProjectId(runtime: Runtime): ProjectId | undefined {
    return lookupProjectId(envLookup(runtime))
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

const NO_HOME_HINT = `Set HOG_HOME to a folder hog can write to, or set HOG_PERSONAL_API_KEY to skip logging in. ${PROJECT_SETTINGS_HINT}.`

function posthogHomeDir(env: Env, homeDir: string | undefined): string | undefined {
    if (env.HOG_HOME) {
        return env.HOG_HOME
    }
    return homeDir === undefined ? undefined : join(homeDir, '.posthog')
}

export function posthogPath(runtime: Pick<Runtime, 'env' | 'homeDir'>, name: string): string | undefined {
    const home = posthogHomeDir(runtime.env, runtime.homeDir())
    return home === undefined ? undefined : join(home, name)
}

export function posthogFile(runtime: Runtime, name: string): string {
    const file = posthogPath(runtime, name)

    if (file === undefined) {
        throw new HogError(
            'no_home_directory',
            "hog couldn't find your home folder to store credentials in.",
            NO_HOME_HINT
        )
    }

    return file
}

export interface CredentialOptions {
    host?: Host
    dotenvFile?: string
    configPath?: string
    configHost?: Host
    configProjectId?: ProjectId
    // For callers that must never open the keychain or get a token, like telemetry.
    envOnly?: boolean
    workloadProviders?: readonly WorkloadProvider[]
}

// What picks the stored login a command uses. Logout uses it too, so it removes the login commands send.
export function loginQuery(
    runtime: Runtime,
    {
        host,
        configPath,
        configHost,
        configProjectId,
    }: Pick<CredentialOptions, 'host' | 'configPath' | 'configHost' | 'configProjectId'>
): LoginQuery {
    return { host, projectId: envProjectId(runtime), configPath, configHost, configProjectId }
}

// Every credential source, in order: HOG_PERSONAL_API_KEY in the environment, then in --dotenv-file,
// then the OIDC token of a CI job that names a project, then what `hog auth login` stored. The global
// host overrides the host a key in the environment or --dotenv-file carried. A stored login is kept
// per host and project, and `chooseLogin` picks it from posthog.json, --host, HOG_HOST and
// HOG_PROJECT_ID. posthog.json comes from the repository, so its host never redirects a key: it can
// pick a stored login for that host, and otherwise only stops the command when the key belongs to
// another host.
export async function resolveCredentials(runtime: Runtime, options: CredentialOptions): Promise<Credentials> {
    const checkConfigHost = (host: Host): void => {
        const { configHost } = options
        if (options.host === undefined && configHost !== undefined && hostKey(configHost) !== hostKey(host)) {
            throw new HogError(
                'host_mismatch',
                `posthog.json sets the host to ${configHost}, but your credentials are for ${host}.`,
                `Pass --host ${configHost} or set HOG_HOST to send your credentials there, or log in to that host with \`hog auth login --host ${configHost}\`.`,
                EXIT_USAGE
            )
        }
    }
    const keyFrom = (raw: RawCredentials): PersonalAPIKey => {
        const failure = { code: 'invalid_credentials' }
        const host = options.host ?? (raw.host === undefined ? DEFAULT_HOST : parseHost(raw.host, failure))
        checkConfigHost(host)
        return new PersonalAPIKey({ host, projectId: raw.projectId, apiKey: parsePersonalApiKey(raw.apiKey, failure) })
    }

    const fromEnv = fromLookup(envLookup(runtime), options.configProjectId)
    if (fromEnv) {
        return { key: keyFrom(fromEnv), source: 'env', storage: null }
    }

    const dotenvFile = options.dotenvFile
    if (dotenvFile) {
        const contents = await readDotenv(runtime, dotenvFile)
        if (contents !== undefined) {
            const values = parseDotenv(contents, dotenvFile)
            const fromFile = fromLookup((name) => values.get(name) || undefined, options.configProjectId)
            if (!fromFile) {
                throw new HogError(
                    'not_authenticated',
                    `hog couldn't find HOG_PERSONAL_API_KEY and a project ID in the environment, posthog.json or ${dotenvFile}.`,
                    `Add HOG_PERSONAL_API_KEY to the file, or remove --dotenv-file. ${PROJECT_SETTINGS_HINT}.`
                )
            }
            return { key: keyFrom(fromFile), source: 'dotenv-file', path: dotenvFile, storage: null }
        }
    }

    const workloadProvider = detectWorkloadProvider(runtime.env, options.workloadProviders)
    const workloadProjectId = workloadProvider && (envProjectId(runtime) ?? options.configProjectId)
    if (!options.envOnly && workloadProvider && workloadProjectId) {
        const key = await exchangeWorkloadToken(runtime, {
            host: workloadHost(options),
            projectId: workloadProjectId,
            provider: workloadProvider,
        })
        if (key) {
            return { key, source: 'workload', storage: new MemoryKeyStorage(key) }
        }
    }

    if (!options.envOnly) {
        const settings = await readSettings(runtime).catch((error: unknown) => {
            // Without a home folder hog has no logins, so the way in is the environment.
            if (error instanceof HogError && error.code === 'no_home_directory') {
                throw new HogError(
                    'not_authenticated',
                    "hog couldn't find PostHog credentials or a home folder to read them from.",
                    `${error.hint} Or set HOG_PERSONAL_API_KEY to skip logging in. ${PROJECT_SETTINGS_HINT}.`
                )
            }
            throw error
        })

        const query = loginQuery(runtime, options)
        const { choice, record } = chooseLogin(settings, query)
        const login = record && (await readLogin(runtime, settings, record))

        if (login) {
            // Before a renewal, so hog never renews a key it then refuses to send.
            checkConfigHost(login.key.host)
            // Logins are kept per origin, so another path on it is another PostHog the login isn't for.
            if (options.host !== undefined && options.host !== login.key.host) {
                throw new HogError(
                    'host_mismatch',
                    `Your login for ${hostKey(options.host)} is for ${login.key.host}, not ${options.host}.`,
                    `Run \`hog auth login --host ${options.host}\` to log in there instead.`,
                    EXIT_USAGE
                )
            }

            const storage = loginStorage(runtime, login)
            const key = await login.key.fresh(runtime, storage)
            const { store } = login

            return { key, source: 'store', store: store.kind, path: store.path, storage, choice }
        }

        if (!record && choice.host !== null && choice.projectId !== null && settings.logins.length > 0) {
            throw new ProjectMismatch(query, { host: choice.host, projectId: choice.projectId }, settings)
        }

        // posthog.json names a host hog has no login to, and the last login is to another host.
        const lastHost = fallbackHost(settings)
        if (!record && lastHost) {
            checkConfigHost(lastHost)
        }
    }

    throw new HogError(
        'not_authenticated',
        "hog couldn't find PostHog credentials.",
        notAuthenticatedHint(workloadProvider, workloadProjectId)
    )
}

// posthog.json comes with the repository, so a host in it outside PostHog Cloud could send a job's token
// to a server that replays it at PostHog. Such a host needs HOG_HOST or --host.
function workloadHost(options: { host?: Host; configHost?: Host }): Host {
    if (options.host !== undefined) {
        return options.host
    }
    if (options.configHost !== undefined && cloudRegion(options.configHost) === undefined) {
        throw new HogError(
            'workload_host_not_allowed',
            `posthog.json names ${options.configHost}, and a CI job sends its token only to PostHog Cloud from posthog.json.`,
            `Set HOG_HOST to ${options.configHost} in the job to send its token there.`,
            EXIT_USAGE
        )
    }
    return cloudRegion(options.configHost) ?? REGIONS.us
}

function notAuthenticatedHint(
    workloadProvider: WorkloadProvider | undefined,
    projectId: ProjectId | undefined
): string {
    if (workloadProvider === undefined) {
        return `Run \`hog auth login\`, or set HOG_PERSONAL_API_KEY. ${PROJECT_SETTINGS_HINT}.`
    }
    const fix = projectId
        ? workloadProvider.missingTokenHint
        : `${PROJECT_SETTINGS_HINT} in the job, so hog can exchange the job's ${workloadProvider.name} OIDC token for a PostHog token.`
    return `${fix} Or set HOG_PERSONAL_API_KEY.`
}
