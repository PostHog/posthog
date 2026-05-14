import { Entry } from '@napi-rs/keyring'
import chalk from 'chalk'
import Conf from 'conf'
import inquirer from 'inquirer'
import { randomUUID } from 'node:crypto'
import ora from 'ora'

import {
    buildAuthorizeUrl,
    exchangeAuthorizationCode,
    fetchOAuthMetadata,
    generatePkce,
    getOAuthScopes,
    openBrowser,
    refreshOAuthToken,
    registerOAuthClient,
    startCallbackServer,
    type OAuthTokenResponse,
} from './oauth.js'

export interface CLIConfig {
    apiKey?: string
    accessToken?: string
    refreshToken?: string
    expiresAt?: number
    clientId?: string
    host?: string
    projectId?: string
}

export interface EnsureAuthOptions {
    projectId?: string
}

const DEFAULT_HOST = 'https://us.posthog.com'
const TOKEN_EXPIRY_SKEW_MS = 60_000

const KEYRING_SERVICE = 'posthog-ph'
const SECRET_KEYS = ['apiKey', 'accessToken', 'refreshToken'] as const
type SecretKey = (typeof SECRET_KEYS)[number]

function isSecretKey(key: keyof CLIConfig): key is SecretKey {
    return (SECRET_KEYS as readonly string[]).includes(key)
}

// Picks the project id to persist alongside a freshly issued OAuth token.
// When the token explicitly scopes a set of teams, only an existingProjectId
// that is *in* that set survives — otherwise we fall back to auto-selecting a
// single scoped team, or returning undefined so the caller re-prompts.
export function resolveProjectId(scopedTeams: number[] | undefined, existingProjectId?: string): string | undefined {
    if (scopedTeams && scopedTeams.length > 0) {
        const scoped = new Set(scopedTeams.map((id) => String(id)))
        if (existingProjectId && scoped.has(existingProjectId)) {
            return existingProjectId
        }
        return scopedTeams.length === 1 ? String(scopedTeams[0]) : undefined
    }
    return existingProjectId
}

interface SecretStore {
    get(key: SecretKey): string | undefined
    set(key: SecretKey, value: string): void
    delete(key: SecretKey): void
    clear(): void
}

class KeyringSecretStore implements SecretStore {
    private readonly entries = new Map<SecretKey, Entry>()

    private entry(key: SecretKey): Entry {
        let cached = this.entries.get(key)
        if (!cached) {
            cached = new Entry(KEYRING_SERVICE, key)
            this.entries.set(key, cached)
        }
        return cached
    }

    get(key: SecretKey): string | undefined {
        try {
            const value = this.entry(key).getPassword()
            return value ?? undefined
        } catch {
            return undefined
        }
    }

    set(key: SecretKey, value: string): void {
        try {
            this.entry(key).setPassword(value)
        } catch (err) {
            throw new Error(`Failed to store credential '${key}' in the OS keychain`, { cause: err })
        }
    }

    delete(key: SecretKey): void {
        try {
            this.entry(key).deletePassword()
        } catch {
            // Already absent or backend unavailable; nothing to do.
        }
    }

    clear(): void {
        for (const key of SECRET_KEYS) {
            this.delete(key)
        }
    }
}

class FileSecretStore implements SecretStore {
    constructor(private readonly conf: Conf<CLIConfig>) {}

    get(key: SecretKey): string | undefined {
        const value = this.conf.get(key)
        return typeof value === 'string' && value.length > 0 ? value : undefined
    }

    set(key: SecretKey, value: string): void {
        this.conf.set(key, value)
    }

    delete(key: SecretKey): void {
        this.conf.delete(key)
    }

    clear(): void {
        for (const key of SECRET_KEYS) {
            this.conf.delete(key)
        }
    }
}

// Probes the OS keychain to decide which backend to use. On Linux this fails
// when libsecret / Secret Service isn't available; in that case we fall back
// to the plaintext Conf file so headless / CI environments still work.
function createSecretStore(conf: Conf<CLIConfig>): { store: SecretStore; backend: 'keyring' | 'file' } {
    try {
        new Entry(KEYRING_SERVICE, '__posthog-cli-probe__').getPassword()
        return { store: new KeyringSecretStore(), backend: 'keyring' }
    } catch {
        return { store: new FileSecretStore(conf), backend: 'file' }
    }
}

export class ConfigManager {
    private conf: Conf<CLIConfig>
    private secrets: SecretStore

    constructor() {
        this.conf = new Conf<CLIConfig>({
            projectName: 'posthog-cli-2.0',
            schema: {
                apiKey: { type: 'string' },
                accessToken: { type: 'string' },
                refreshToken: { type: 'string' },
                expiresAt: { type: 'number' },
                clientId: { type: 'string' },
                host: { type: 'string', default: DEFAULT_HOST },
                projectId: { type: 'string' },
            },
        })

        const { store, backend } = createSecretStore(this.conf)
        this.secrets = store

        if (backend === 'keyring') {
            this.migrateLegacySecrets()
        } else {
            console.warn(chalk.dim('⚠ OS keychain unavailable; storing credentials in the config file.'))
        }
    }

    private migrateLegacySecrets(): void {
        for (const key of SECRET_KEYS) {
            try {
                const fileValue = this.conf.get(key)
                if (typeof fileValue !== 'string' || fileValue.length === 0) {
                    continue
                }
                if (this.secrets.get(key)) {
                    this.conf.delete(key)
                    continue
                }
                this.secrets.set(key, fileValue)
                this.conf.delete(key)
            } catch {
                // Migration is best-effort; never block CLI startup on it.
            }
        }
    }

    get(key: keyof CLIConfig): any {
        // Check environment variables first
        switch (key) {
            case 'apiKey':
                return process.env.POSTHOG_CLI_API_KEY || process.env.POSTHOG_API_KEY || this.secrets.get('apiKey')
            case 'accessToken':
                return (
                    process.env.POSTHOG_CLI_ACCESS_TOKEN ||
                    process.env.POSTHOG_ACCESS_TOKEN ||
                    this.secrets.get('accessToken')
                )
            case 'refreshToken':
                return process.env.POSTHOG_CLI_REFRESH_TOKEN || this.secrets.get('refreshToken')
            case 'clientId':
                return process.env.POSTHOG_CLI_CLIENT_ID || this.conf.get(key)
            case 'expiresAt':
                return process.env.POSTHOG_CLI_EXPIRES_AT
                    ? Number(process.env.POSTHOG_CLI_EXPIRES_AT)
                    : this.conf.get(key)
            case 'host':
                return process.env.POSTHOG_CLI_HOST || process.env.POSTHOG_HOST || this.conf.get(key)
            case 'projectId':
                return process.env.POSTHOG_CLI_PROJECT_ID || process.env.POSTHOG_PROJECT_ID || this.conf.get(key)
            default:
                return this.conf.get(key)
        }
    }

    set(key: keyof CLIConfig, value: any): void {
        if (isSecretKey(key)) {
            if (typeof value === 'string' && value.length > 0) {
                this.secrets.set(key, value)
            } else {
                this.secrets.delete(key)
            }
            return
        }
        this.conf.set(key, value)
    }

    getAll(): CLIConfig {
        return {
            apiKey: this.get('apiKey'),
            accessToken: this.get('accessToken'),
            refreshToken: this.get('refreshToken'),
            expiresAt: this.get('expiresAt'),
            clientId: this.get('clientId'),
            host: this.get('host'),
            projectId: this.get('projectId'),
        }
    }

    async ensureAuth(options: EnsureAuthOptions = {}): Promise<CLIConfig> {
        const projectIdOverride = this.normalizeProjectIdOverride(options.projectId)
        const currentConfig = this.getAll()

        const refreshedConfig = await this.refreshIfNeeded(currentConfig)
        const commandConfig = projectIdOverride ? { ...refreshedConfig, projectId: projectIdOverride } : refreshedConfig
        if (commandConfig.accessToken) {
            return projectIdOverride ? commandConfig : this.ensureProject(commandConfig)
        }

        if (currentConfig.apiKey) {
            const apiKeyConfig = { ...commandConfig, accessToken: undefined }
            return projectIdOverride ? apiKeyConfig : this.ensureProject(apiKeyConfig)
        }

        return this.login(projectIdOverride)
    }

    async login(projectIdOverride?: string): Promise<CLIConfig> {
        console.log(chalk.yellow('\n🔐 Authentication required'))
        console.log('Opening PostHog OAuth login in your browser...')

        // An explicit login is a fresh session — drop the stored project so we
        // re-resolve it from the new token's scope rather than reusing a stale
        // id the new grant may not have access to.
        this.conf.delete('projectId')

        const oauthConfig = await this.loginWithOAuth()
        const normalizedProjectIdOverride = this.normalizeProjectIdOverride(projectIdOverride)
        if (normalizedProjectIdOverride) {
            return { ...oauthConfig, projectId: normalizedProjectIdOverride }
        }

        return this.ensureProject(oauthConfig)
    }

    clear(): void {
        this.conf.clear()
        this.secrets.clear()
        console.log(chalk.green('✅ Configuration cleared!'))
    }

    private normalizeProjectIdOverride(projectId: string | undefined): string | undefined {
        const normalizedProjectId = projectId?.trim()
        return normalizedProjectId && normalizedProjectId.length > 0 ? normalizedProjectId : undefined
    }

    private async refreshIfNeeded(config: CLIConfig): Promise<CLIConfig> {
        if (!config.accessToken) {
            return config
        }

        if (!config.expiresAt || config.expiresAt > Date.now() + TOKEN_EXPIRY_SKEW_MS) {
            return config
        }

        if (!config.refreshToken || !config.clientId) {
            return { ...config, accessToken: undefined }
        }

        const spinner = ora('Refreshing PostHog OAuth token...').start()
        try {
            const token = await refreshOAuthToken({ clientId: config.clientId, refreshToken: config.refreshToken })
            const refreshedConfig = this.saveOAuthToken(token, config.clientId, config.projectId)
            spinner.succeed('OAuth token refreshed')
            return refreshedConfig
        } catch (error) {
            spinner.warn('OAuth token refresh failed; please log in again')
            this.secrets.delete('accessToken')
            this.secrets.delete('refreshToken')
            this.conf.delete('expiresAt')
            this.conf.delete('clientId')
            return {
                ...config,
                accessToken: undefined,
                refreshToken: undefined,
                expiresAt: undefined,
                clientId: undefined,
            }
        }
    }

    private async loginWithOAuth(): Promise<CLIConfig> {
        const state = randomUUID()
        const callbackServer = await startCallbackServer(state)

        try {
            const metadata = await fetchOAuthMetadata()
            const client = await registerOAuthClient(metadata, callbackServer.redirectUri)
            const { codeVerifier, codeChallenge } = generatePkce()
            const authorizeUrl = buildAuthorizeUrl({
                metadata,
                clientId: client.client_id,
                redirectUri: callbackServer.redirectUri,
                state,
                codeChallenge,
                scopes: getOAuthScopes(),
            })

            console.log(chalk.dim(`If the browser does not open, visit:\n${authorizeUrl}\n`))
            openBrowser(authorizeUrl)

            const code = await callbackServer.waitForCallback
            const spinner = ora('Exchanging authorization code...').start()
            try {
                const token = await exchangeAuthorizationCode({
                    metadata,
                    clientId: client.client_id,
                    code,
                    redirectUri: callbackServer.redirectUri,
                    codeVerifier,
                })
                const savedConfig = this.saveOAuthToken(token, client.client_id)
                spinner.succeed('Authentication saved')
                return savedConfig
            } catch (error) {
                spinner.fail('OAuth token exchange failed')
                throw error
            }
        } finally {
            await callbackServer.close()
        }
    }

    private saveOAuthToken(token: OAuthTokenResponse, clientId: string, existingProjectId?: string): CLIConfig {
        const expiresAt = token.expires_in ? Date.now() + token.expires_in * 1000 : undefined
        const host = token.posthog_base_url || this.get('host') || DEFAULT_HOST
        const projectId = resolveProjectId(token.scoped_teams, existingProjectId)

        this.set('accessToken', token.access_token)
        this.set('clientId', clientId)
        this.set('host', host)

        if (token.refresh_token) {
            this.set('refreshToken', token.refresh_token)
        }
        if (expiresAt) {
            this.set('expiresAt', expiresAt)
        }
        if (projectId) {
            this.set('projectId', projectId)
        } else {
            // Drop any stale projectId from the previous grant so ensureProject
            // re-resolves instead of letting downstream calls 403 on a project
            // the new token can't access.
            this.conf.delete('projectId')
        }

        return this.getAll()
    }

    private async ensureProject(config: CLIConfig): Promise<CLIConfig> {
        if (config.projectId) {
            return config
        }

        const projects = await this.fetchAccessibleProjects(config)
        if (projects.length === 1) {
            const projectId = String(projects[0].id)
            this.set('projectId', projectId)
            console.log(chalk.green(`✅ Using project: ${projects[0].name || projectId} (${projectId})`))
            return { ...config, projectId }
        }

        if (projects.length > 1) {
            const answers = await inquirer.prompt([
                {
                    type: 'list',
                    name: 'projectId',
                    message: 'Select a PostHog project:',
                    choices: projects.map((project) => ({
                        name: `${project.name || `Project ${project.id}`} (${project.id})`,
                        value: String(project.id),
                    })),
                },
            ])

            this.set('projectId', answers.projectId)
            return { ...config, projectId: answers.projectId }
        }

        const answers = await inquirer.prompt([
            {
                type: 'input',
                name: 'projectId',
                message: 'Project ID (from URL like /project/12345):',
                validate: (input) => {
                    if (!input || input.trim() === '') {
                        return 'Project ID is required'
                    }
                    return true
                },
            },
        ])

        this.set('projectId', answers.projectId)
        return { ...config, projectId: answers.projectId }
    }

    private async fetchAccessibleProjects(config: CLIConfig): Promise<Array<{ id: number | string; name?: string }>> {
        const token = config.accessToken || config.apiKey
        const host = config.host || DEFAULT_HOST
        if (!token) {
            return []
        }

        try {
            const url = new URL('/api/projects/', host)
            url.searchParams.set('limit', '100')

            const response = await fetch(url.toString(), {
                headers: {
                    Authorization: `Bearer ${token}`,
                    'Content-Type': 'application/json',
                    'User-Agent': 'PostHog-CLI-2.0/0.1.0',
                },
            })

            if (!response.ok) {
                return []
            }

            const data = (await response.json()) as
                | { results?: Array<{ id: number | string; name?: string }> }
                | Array<{ id: number | string; name?: string }>
            return Array.isArray(data) ? data : data.results || []
        } catch {
            return []
        }
    }
}

export const config = new ConfigManager()
