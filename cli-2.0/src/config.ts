import { randomUUID } from 'node:crypto'
import Conf from 'conf'
import inquirer from 'inquirer'
import chalk from 'chalk'
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

const DEFAULT_HOST = 'https://us.posthog.com'
const TOKEN_EXPIRY_SKEW_MS = 60_000

export class ConfigManager {
  private conf: Conf<CLIConfig>

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
        projectId: { type: 'string' }
      }
    })
  }

  get(key: keyof CLIConfig): any {
    // Check environment variables first
    switch (key) {
      case 'apiKey':
        return process.env.POSTHOG_CLI_API_KEY || process.env.POSTHOG_API_KEY || this.conf.get(key)
      case 'accessToken':
        return process.env.POSTHOG_CLI_ACCESS_TOKEN || process.env.POSTHOG_ACCESS_TOKEN || this.conf.get(key)
      case 'refreshToken':
        return process.env.POSTHOG_CLI_REFRESH_TOKEN || this.conf.get(key)
      case 'clientId':
        return process.env.POSTHOG_CLI_CLIENT_ID || this.conf.get(key)
      case 'expiresAt':
        return process.env.POSTHOG_CLI_EXPIRES_AT ? Number(process.env.POSTHOG_CLI_EXPIRES_AT) : this.conf.get(key)
      case 'host':
        return process.env.POSTHOG_CLI_HOST || process.env.POSTHOG_HOST || this.conf.get(key)
      case 'projectId':
        return process.env.POSTHOG_CLI_PROJECT_ID || process.env.POSTHOG_PROJECT_ID || this.conf.get(key)
      default:
        return this.conf.get(key)
    }
  }

  set(key: keyof CLIConfig, value: any): void {
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
      projectId: this.get('projectId')
    }
  }

  async ensureAuth(): Promise<CLIConfig> {
    const currentConfig = this.getAll()

    const refreshedConfig = await this.refreshIfNeeded(currentConfig)
    if (refreshedConfig.accessToken) {
      return this.ensureProject(refreshedConfig)
    }

    if (currentConfig.apiKey) {
      return this.ensureProject({ ...currentConfig, accessToken: undefined })
    }

    return this.login()
  }

  async login(): Promise<CLIConfig> {
    console.log(chalk.yellow('\n🔐 Authentication required'))
    console.log('Opening PostHog OAuth login in your browser...')

    const oauthConfig = await this.loginWithOAuth()
    return this.ensureProject(oauthConfig)
  }

  clear(): void {
    this.conf.clear()
    console.log(chalk.green('✅ Configuration cleared!'))
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
      this.conf.delete('accessToken')
      this.conf.delete('refreshToken')
      this.conf.delete('expiresAt')
      this.conf.delete('clientId')
      return { ...config, accessToken: undefined, refreshToken: undefined, expiresAt: undefined, clientId: undefined }
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
    const projectId = existingProjectId || this.inferProjectId(token.scoped_teams)

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
    }

    return this.getAll()
  }

  private inferProjectId(scopedTeams: number[] | undefined): string | undefined {
    if (!scopedTeams || scopedTeams.length !== 1) {
      return undefined
    }
    return String(scopedTeams[0])
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
        }
      }
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

      const data = await response.json() as { results?: Array<{ id: number | string; name?: string }> } | Array<{ id: number | string; name?: string }>
      return Array.isArray(data) ? data : data.results || []
    } catch {
      return []
    }
  }
}

export const config = new ConfigManager()
