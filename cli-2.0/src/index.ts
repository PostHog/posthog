#!/usr/bin/env node

import yargs from 'yargs'
import { hideBin } from 'yargs/helpers'
import chalk from 'chalk'
import ora from 'ora'
import { config } from './config.js'
import { createMCPContext, type AuthenticatedConfig, type Context } from './mcp-context.js'
import { commands, enhancedMappingsMeta, executeCommand, executeToolCall } from './generated/commands.js'
import { printResult } from './output.js'

function isTopLevelCommandGroupHelpRequest(argv: { _: Array<string | number> }): boolean {
  if (argv._.length !== 1) {
    return false
  }

  const command = String(argv._[0])
  return command === 'auth' || Object.prototype.hasOwnProperty.call(commands, command)
}


async function main() {
  let authCommandHelp: (() => void) | undefined
  const commandGroupHelp = new Map<string, () => void>()

  const cli = yargs(hideBin(process.argv))
    .scriptName('ph')
    .usage('$0 <command> [options]')
    .help()
    .version('0.1.0')
    .wrap(120)
    .option('json', {
      type: 'boolean',
      describe: 'Output raw JSON without terminal formatting',
      default: false,
    })
    .demandCommand(1, 'You need at least one command before moving on')
    .fail((msg, err, yargs) => {
      if (err) throw err
      console.error(chalk.red(msg))
      console.error(yargs.help())
      process.exit(1)
    })
    .middleware(async (argv: any & { mcpContext?: Context }) => {
      // Skip setup for help/version/auth commands and bare command groups that show help.
      const isHelpCommand = argv.help || argv.h || argv._.includes('help')
      const isVersionCommand = argv.version || argv.v
      const isAuthCommand = argv._[0] === 'auth'
      const isCommandGroupHelpRequest = isTopLevelCommandGroupHelpRequest(argv)
      
      if (isHelpCommand || isVersionCommand || isAuthCommand || isCommandGroupHelpRequest) {
        return
      }
      
      const authConfig = await config.ensureAuth()
      
      if ((!authConfig.accessToken && !authConfig.apiKey) || !authConfig.projectId || !authConfig.host) {
        console.error(chalk.red('Missing configuration. Run: ph auth login'))
        process.exit(1)
      }

      // Create context for API calls
      argv.mcpContext = createMCPContext(authConfig as AuthenticatedConfig)
    })
    
    // Auth commands
    .command('auth', 'Authentication commands', (yargs) => {
      const authCommands = yargs
        .command('login', 'Login to PostHog with OAuth', {}, async () => {
          config.clear()
          await config.login()
        })
        .command('logout', 'Clear stored credentials', {}, () => {
          config.clear()
        })
        .command('status', 'Show authentication status', {}, () => {
          const cfg = config.getAll()
          console.log('Authentication status:')
          console.log('OAuth Access Token:', cfg.accessToken ? '✅ Set' : '❌ Not set')
          console.log('OAuth Refresh Token:', cfg.refreshToken ? '✅ Set' : '❌ Not set')
          console.log('API Key:', cfg.apiKey ? '✅ Set (from legacy config/env)' : '❌ Not set')
          console.log('Host:', cfg.host || '❌ Not set')
          console.log('Project ID:', cfg.projectId || '❌ Not set')
        })

      authCommandHelp = () => authCommands.showHelp()
      return authCommands
    }, () => {
      authCommandHelp?.() ?? cli.showHelp()
    })
    
    // Add human-readable commands from the new command mappings
  
  for (const [commandName, command] of Object.entries(commands)) {
    if (Object.keys(command.subcommands).length === 0) continue // Skip empty commands
    
    // Create the main command with aliases
    const commandAliases = command.aliases || []
    const commandSpec = [commandName, ...commandAliases]
    
    cli.command(commandSpec, command.description, (yargs) => {
      let subCommands = yargs.demandCommand(1, 'You need to specify a subcommand')
      
      // Add each subcommand
      for (const [subcommandName, subcommand] of Object.entries(command.subcommands)) {
        const subcommandAliases = subcommand.aliases || []
        const subcommandSpec = [subcommandName, ...subcommandAliases]
        
        subCommands = subCommands.command(
          [subcommandName, ...subcommandAliases],
          subcommand.description,
          (yargs) => {
            return yargs
              .option('id', {
                type: 'string',
                describe: 'Resource ID'
              })
              .strict(false) // Allow additional parameters
          },
          async (argv) => {
            const params: any = {}
            // Pass through all arguments except the internal ones
            for (const [key, value] of Object.entries(argv)) {
              if (key !== '_' && key !== '$0' && key !== 'mcpContext') {
                params[key] = value
              }
            }
            await executeGeneratedTool(argv, subcommand.mcp_tool, params)
          }
        )
      }
      
      commandGroupHelp.set(commandName, () => subCommands.showHelp())
      return subCommands
    }, () => {
      commandGroupHelp.get(commandName)?.() ?? cli.showHelp()
    })
  }
    
  // Direct API access
  cli.command('api <method> <path>', 'Make direct API calls', {
      method: { 
        type: 'string', 
        describe: 'HTTP method',
        choices: ['GET', 'POST', 'PATCH', 'PUT', 'DELETE']
      },
      path: { type: 'string', describe: 'API path' },
      body: { type: 'string', describe: 'Request body as JSON' },
      query: { type: 'string', describe: 'Query parameters as JSON' }
    }, async (argv) => {
      const spinner = ora(`Making ${argv.method} request to ${argv.path}...`).start()
      
      try {
        const body = argv.body ? JSON.parse(argv.body) : undefined
        const query = argv.query ? JSON.parse(argv.query) : undefined
        
        const result = await (argv.mcpContext as Context).api.request({
          method: argv.method as any,
          path: argv.path!,
          body,
          query
        })
        
        spinner.succeed('API call completed')
        printResult(argv, 'api', result)
      } catch (error: any) {
        spinner.fail('API call failed')
        console.error(chalk.red('Error:'), error.message)
        process.exit(1)
      }
    })

  await cli.parse()
}

async function executeGeneratedTool(argv: any, toolName: string, params: any) {
  const spinner = ora(`Executing ${toolName}...`).start()
  
  try {
    const result = await executeToolCall(argv.mcpContext as Context, toolName, params)
    
    spinner.succeed('Command completed')
    printResult(argv, toolName, result)
  } catch (error: any) {
    spinner.fail('Command failed')
    console.error(chalk.red('Error:'), error.message)
    process.exit(1)
  }
}

main().catch(console.error)