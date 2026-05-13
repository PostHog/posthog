#!/usr/bin/env node

import yargs from 'yargs'
import { hideBin } from 'yargs/helpers'
import chalk from 'chalk'
import ora from 'ora'
import { highlight } from 'cli-highlight'
import Table from 'cli-table3'
import { config } from './config.js'
import { createMCPContext, type AuthenticatedConfig, type Context } from './mcp-context.js'
import { commands, enhancedMappingsMeta, executeCommand, executeToolCall } from './generated/commands.js'

type JsonRecord = Record<string, unknown>

type TableColumn = {
  header: string
  render: (item: JsonRecord) => string
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function getListItems(result: unknown): JsonRecord[] {
  if (Array.isArray(result)) {
    return result.filter(isRecord)
  }

  if (isRecord(result) && Array.isArray(result.results)) {
    return result.results.filter(isRecord)
  }

  return []
}

function getResultCount(result: unknown): number | undefined {
  if (!isRecord(result) || typeof result.count !== 'number') {
    return undefined
  }

  return result.count
}

function stringify(value: unknown): string {
  if (value === null || value === undefined) {
    return ''
  }

  if (typeof value === 'string') {
    return value.replace(/[\u0000-\u001F\u007F-\u009F]/g, '')
  }

  return String(value)
}

function truncate(value: string, maxLength: number): string {
  if (value.length <= maxLength) {
    return value
  }

  return `${value.slice(0, maxLength - 1)}…`
}

function printRawJson(result: unknown): void {
  console.log(JSON.stringify(result, null, 2))
}

function printPrettyJson(result: unknown): void {
  const json = JSON.stringify(result, null, 2)

  if (!process.stdout.isTTY) {
    console.log(json)
    return
  }

  console.log(highlight(json, { language: 'json', ignoreIllegals: true }))
}

function printListTable(result: unknown, emptyMessage: string, columns: TableColumn[]): void {
  if (!process.stdout.isTTY) {
    printPrettyJson(result)
    return
  }

  const items = getListItems(result)

  if (items.length === 0) {
    console.log(chalk.gray(emptyMessage))
    return
  }

  const table = new Table({
    head: columns.map((column) => column.header),
    wordWrap: true,
    wrapOnWordBoundary: false,
  })

  for (const item of items) {
    table.push(columns.map((column) => column.render(item)))
  }

  console.log(table.toString())

  const count = getResultCount(result)
  if (count !== undefined && count !== items.length) {
    console.log(chalk.gray(`Showing ${items.length} of ${count}`))
  }
}

function printFeatureFlags(result: unknown): void {
  printListTable(result, 'No feature flags found.', [
    { header: 'ID', render: (flag) => stringify(flag.id) },
    { header: 'Key', render: (flag) => stringify(flag.key) },
    { header: 'Name', render: (flag) => stringify(flag.name) },
    {
      header: 'Status',
      render: (flag) => flag.active ? chalk.green('active') : chalk.gray('inactive'),
    },
  ])
}

function printInsights(result: unknown): void {
  printListTable(result, 'No insights found.', [
    { header: 'ID', render: (insight) => stringify(insight.id) },
    { header: 'Short ID', render: (insight) => stringify(insight.short_id) },
    { header: 'Name', render: (insight) => truncate(stringify(insight.name), 60) },
    { header: 'Type', render: (insight) => stringify(isRecord(insight.query) ? insight.query.kind : '') },
  ])
}

function printDashboards(result: unknown): void {
  printListTable(result, 'No dashboards found.', [
    { header: 'ID', render: (dashboard) => stringify(dashboard.id) },
    { header: 'Name', render: (dashboard) => truncate(stringify(dashboard.name), 60) },
    { header: 'Description', render: (dashboard) => truncate(stringify(dashboard.description), 80) },
  ])
}

function printHumanResult(toolName: string, result: unknown): void {
  switch (toolName) {
    case 'feature-flag-get-all':
      printFeatureFlags(result)
      return
    case 'insight-get-all':
      printInsights(result)
      return
    case 'dashboard-get-all':
      printDashboards(result)
      return
    default:
      printPrettyJson(result)
  }
}

function printResult(argv: unknown, toolName: string, result: unknown): void {
  if (isRecord(argv) && argv.json === true) {
    printRawJson(result)
    return
  }

  printHumanResult(toolName, result)
}

async function main() {
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
      // Skip setup for help/version/auth commands
      const isHelpCommand = argv.help || argv.h || argv._.includes('help')
      const isVersionCommand = argv.version || argv.v
      const isAuthCommand = argv._[0] === 'auth'
      
      if (isHelpCommand || isVersionCommand || isAuthCommand) {
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
        .demandCommand(1, 'You need to specify a subcommand')
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
      
      return subCommands
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