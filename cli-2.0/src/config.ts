import Conf from 'conf'
import inquirer from 'inquirer'
import chalk from 'chalk'

export interface CLIConfig {
  apiKey?: string
  host?: string
  projectId?: string
}

export class ConfigManager {
  private conf: Conf<CLIConfig>

  constructor() {
    this.conf = new Conf<CLIConfig>({
      projectName: 'posthog-cli-2.0',
      schema: {
        apiKey: { type: 'string' },
        host: { type: 'string', default: 'https://us.posthog.com' },
        projectId: { type: 'string' }
      }
    })
  }

  get(key: keyof CLIConfig): any {
    // Check environment variables first
    switch (key) {
      case 'apiKey':
        return process.env.POSTHOG_CLI_API_KEY || process.env.POSTHOG_API_KEY || this.conf.get(key)
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
      host: this.get('host'),
      projectId: this.get('projectId')
    }
  }

  async ensureAuth(): Promise<CLIConfig> {
    const config = this.getAll()

    if (!config.apiKey || !config.projectId) {
      console.log(chalk.yellow('\n🔐 Authentication required'))
      console.log('You can get a Personal API key from: https://app.posthog.com/settings/user-api-keys')

      const answers = await inquirer.prompt([
        {
          type: 'input',
          name: 'apiKey',
          message: 'Enter your PostHog Personal API key:',
          validate: (input) => {
            if (!input.startsWith('phx_')) {
              return 'API key must start with "phx_"'
            }
            return true
          },
          when: !config.apiKey
        },
        {
          type: 'input',
          name: 'host',
          message: 'PostHog host:',
          default: 'https://us.posthog.com',
          when: !config.host
        },
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
          when: !config.projectId
        }
      ])

      if (answers.apiKey) {
        this.set('apiKey', answers.apiKey)
        config.apiKey = answers.apiKey
      }
      if (answers.host) {
        this.set('host', answers.host)
        config.host = answers.host
      }
      if (answers.projectId) {
        this.set('projectId', answers.projectId)
        config.projectId = answers.projectId
      }

      console.log(chalk.green('✅ Authentication saved!'))
    }

    return config
  }

  clear(): void {
    this.conf.clear()
    console.log(chalk.green('✅ Configuration cleared!'))
  }
}

export const config = new ConfigManager()