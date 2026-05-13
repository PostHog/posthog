#!/usr/bin/env node

import yargs from 'yargs'
import { hideBin } from 'yargs/helpers'
import chalk from 'chalk'
import ora from 'ora'
import { config } from './config.js'
import { createMCPContext, type AuthenticatedConfig, type Context } from './mcp-context.js'
import { commandGroups, executeToolCall } from './generated/commands.js'
import { printResult } from './output.js'

function isTopLevelCommandGroupHelpRequest(argv: { _: Array<string | number> }): boolean {
  if (argv._.length !== 1) {
    return false
  }

  const command = String(argv._[0])
  return command === 'auth' || Object.prototype.hasOwnProperty.call(commandGroups, command)
}

function stripGroupPrefix(toolName: string, groupName: string): string {
  const groupPrefix = groupName.replace(/-/g, '-')
  const groupSingular = groupPrefix.replace(/s$/, '')

  if (toolName.startsWith(groupSingular + '-')) {
    return toolName.substring(groupSingular.length + 1)
  }

  if (toolName.startsWith(groupPrefix + '-')) {
    return toolName.substring(groupPrefix.length + 1)
  }

  return toolName
}

function getCommandName(toolName: string, groupName: string): string {
  let commandName = stripGroupPrefix(toolName, groupName)
  const groupSingular = groupName.replace(/-/g, '-').replace(/s$/, '')

  if (commandName.startsWith('create-' + groupSingular)) {
    commandName = commandName.replace('create-' + groupSingular, 'create')
  } else if (commandName.startsWith('delete-' + groupSingular)) {
    commandName = commandName.replace('delete-' + groupSingular, 'delete')
  } else if (commandName.startsWith('update-' + groupSingular)) {
    commandName = commandName.replace('update-' + groupSingular, 'update')
  }

  return commandName
}

function getCommandAliases(commandName: string): string[] {
  if (commandName === 'list' || commandName.includes('get-all')) {
    return ['ls']
  }

  if (commandName === 'get' || commandName.includes('retrieve')) {
    return ['show']
  }

  if (commandName === 'create') {
    return ['new']
  }

  if (commandName === 'update' || commandName.includes('partial-update')) {
    return ['edit']
  }

  if (commandName === 'delete' || commandName === 'destroy') {
    return ['remove', 'rm']
  }

  if (commandName === 'launch') {
    return ['start']
  }

  if (commandName === 'end') {
    return ['stop']
  }

  return []
}

async function main() {
  const cli = yargs(hideBin(process.argv))
    .scriptName('ph')
    .usage('$0 <command> [options]')
    .help()
    .version('0.1.0')
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
      return yargs
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
    }, () => {
      cli.showHelp()
    })
    
    // Add generated commands dynamically
  
  // Add all command groups
  for (const [groupName, group] of Object.entries(commandGroups)) {
    if (group.tools.length === 0) continue // Skip empty groups
    
    cli.command(groupName, `${groupName.charAt(0).toUpperCase() + groupName.slice(1).replace('-', ' ')} commands`, (yargs) => {
      let subCommands = yargs
      
      // Add each tool as a subcommand with friendly aliases
      for (const tool of group.tools) {
        const commandName = getCommandName(tool.name, groupName)
        const aliases = getCommandAliases(commandName)
        const description = tool.description || `Execute ${tool.name}`
        
        subCommands = subCommands.command(
          [commandName, ...aliases], 
          description.split('\n')[0], // Use first line of description
          {
            id: commandName === 'get' || commandName === 'delete' || commandName === 'update' ? 
              { type: 'string', describe: 'Resource ID', demandOption: true } : 
              { type: 'string', describe: 'Resource ID (optional)' }
          },
          async (argv) => {
            const params: any = {}
            if (argv.id) params.id = argv.id
            await executeGeneratedTool(argv, tool.name, params)
          }
        )
      }
      
      return subCommands
    }, () => {
      cli.showHelp()
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