#!/usr/bin/env node

import yargs from 'yargs'
import { hideBin } from 'yargs/helpers'
import chalk from 'chalk'
import ora from 'ora'
import { highlight } from 'cli-highlight'
import Table from 'cli-table3'
// @ts-expect-error — asciichart ships no type declarations
import asciichart from 'asciichart'
import { config } from './config.js'
import { createMCPContext, type AuthenticatedConfig, type Context } from './mcp-context.js'
import { commandGroups, executeToolCall } from './generated/commands.js'
import {
  buildLabelRow,
  type ChartSeries,
  formatYValue,
  getInsightType,
  isChartSeries,
  isRecord,
  type JsonRecord,
  pickStep,
  stringify,
  widenSeries,
} from './insight-display.js'

type TableColumn = {
  header: string
  render: (item: JsonRecord) => string
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

// asciichart wants raw SGR strings on its `colors` config; chalk 5 doesn't
// expose `.open`, so we keep two parallel constants — one for asciichart, one
// for legend bullets. Same ordering in both.
const CHART_COLORS = [
  { ansi: asciichart.blue, fn: chalk.blue },
  { ansi: asciichart.green, fn: chalk.green },
  { ansi: asciichart.yellow, fn: chalk.yellow },
  { ansi: asciichart.magenta, fn: chalk.magenta },
  { ansi: asciichart.cyan, fn: chalk.cyan },
  { ansi: asciichart.red, fn: chalk.red },
]

function plotTrendsSeries(series: ChartSeries[]): void {
  const points = series[0].data.length
  if (points < 2) {
    console.log(chalk.gray('Not enough data points to plot.'))
    return
  }

  const termWidth = Math.max(60, Math.min(process.stdout.columns ?? 100, 200))
  const step = pickStep(points, termWidth)

  const numericSeries = series.map((s) => widenSeries(s.data.map((v) => Number(v) || 0), step))

  const chart = asciichart.plot(numericSeries.length === 1 ? numericSeries[0] : numericSeries, {
    height: 12,
    colors: numericSeries.map((_, i) => CHART_COLORS[i % CHART_COLORS.length].ansi),
    format: (x: number) => formatYValue(x).padStart(5, ' '),
  })

  console.log(chart)
  console.log(buildLabelRow(series[0].labels, step))
  console.log('')

  series.forEach((s, i) => {
    const { fn: color } = CHART_COLORS[i % CHART_COLORS.length]
    const action = isRecord(s.action) ? s.action : null
    const name = stringify(s.label) || (action ? stringify(action.name) : '') || `Series ${i + 1}`
    const total = typeof s.count === 'number' ? chalk.gray(`  total: ${s.count}`) : ''
    console.log(`  ${color('●')} ${name}${total}`)
  })
}

function printInsightDetail(result: unknown): void {
  if (!isRecord(result)) {
    printPrettyJson(result)
    return
  }

  const name = stringify(result.name) || stringify(result.derived_name) || '(untitled insight)'
  const description = stringify(result.description)

  console.log('')
  console.log(chalk.bold(name))
  if (description) {
    console.log(chalk.gray(description))
  }
  const meta: string[] = []
  if (result.id !== undefined) {
    meta.push(`id: ${stringify(result.id)}`)
  }
  if (result.short_id) {
    meta.push(`short_id: ${stringify(result.short_id)}`)
  }
  meta.push(`type: ${getInsightType(result)}`)
  if (isRecord(result.resolved_date_range)) {
    const from = stringify(result.resolved_date_range.date_from).slice(0, 10)
    const to = stringify(result.resolved_date_range.date_to).slice(0, 10)
    if (from && to) {
      meta.push(`range: ${from} → ${to}`)
    }
  }
  console.log(chalk.gray(meta.join('  ·  ')))
  console.log('')

  const seriesData = Array.isArray(result.result) ? result.result : []
  const plottable = seriesData.filter(isChartSeries)

  if (plottable.length === 0) {
    console.log(chalk.gray('No trends-style result to plot — showing JSON:'))
    console.log('')
    printPrettyJson(result)
    return
  }

  plotTrendsSeries(plottable)
  console.log('')
}

function printHumanResult(toolName: string, result: unknown): void {
  switch (toolName) {
    case 'feature-flag-get-all':
      printFeatureFlags(result)
      return
    case 'insight-get-all':
      printInsights(result)
      return
    case 'insight-get':
      printInsightDetail(result)
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
    
    // Add generated commands dynamically
  
  // Add all command groups
  for (const [groupName, group] of Object.entries(commandGroups)) {
    if (group.tools.length === 0) continue // Skip empty groups
    
    cli.command(groupName, `${groupName.charAt(0).toUpperCase() + groupName.slice(1).replace('-', ' ')} commands`, (yargs) => {
      let subCommands = yargs.demandCommand(1, 'You need to specify a subcommand')
      
      // Add each tool as a subcommand with friendly aliases
      for (const tool of group.tools) {
        let commandName = tool.name
        let aliases: string[] = []
        
        // Use the exact tool name, just remove the feature prefix if present
        commandName = tool.name
        
        // Remove feature prefix if the tool name starts with the group name
        const groupPrefix = groupName.replace(/-/g, '-') // keep dashes for matching
        const groupSingular = groupPrefix.replace(/s$/, '') // remove trailing 's' for singular
        
        if (commandName.startsWith(groupSingular + '-')) {
          commandName = commandName.substring(groupSingular.length + 1)
        } else if (commandName.startsWith(groupPrefix + '-')) {
          commandName = commandName.substring(groupPrefix.length + 1)
        }
        
        // Also check for create-/delete-/update- patterns that reference the feature
        if (commandName.startsWith('create-' + groupSingular)) {
          commandName = commandName.replace('create-' + groupSingular, 'create')
        } else if (commandName.startsWith('delete-' + groupSingular)) {
          commandName = commandName.replace('delete-' + groupSingular, 'delete')
        } else if (commandName.startsWith('update-' + groupSingular)) {
          commandName = commandName.replace('update-' + groupSingular, 'update')
        }
        
        // Set aliases based on common patterns
        aliases = []
        if (commandName === 'list' || commandName.includes('get-all')) {
          aliases = ['ls']
        } else if (commandName === 'get' || commandName.includes('retrieve')) {
          aliases = ['show']
        } else if (commandName === 'create') {
          aliases = ['new']
        } else if (commandName === 'update' || commandName.includes('partial-update')) {
          aliases = ['edit']
        } else if (commandName === 'delete' || commandName === 'destroy') {
          aliases = ['remove', 'rm']
        } else if (commandName === 'launch') {
          aliases = ['start']
        } else if (commandName === 'end') {
          aliases = ['stop']
        }
        
        const description = tool.description || `Execute ${tool.name}`
        
        const requiresId = commandName === 'get' || commandName === 'delete' || commandName === 'update'
        const commandSpec = requiresId ? `${commandName} <id>` : commandName
        
        subCommands = subCommands.command(
          [commandSpec, ...aliases.map(alias => requiresId ? `${alias} <id>` : alias)], 
          description.split('\n')[0], // Use first line of description
          (yargs) => {
            if (requiresId) {
              return yargs.positional('id', {
                type: 'string',
                describe: 'Resource ID',
                demandOption: true
              })
            }
            return yargs
          },
          async (argv) => {
            const params: any = {}
            // Pass through all arguments except the internal ones
            for (const [key, value] of Object.entries(argv)) {
              if (key !== '_' && key !== '$0' && key !== 'mcpContext') {
                params[key] = value
              }
            }
            await executeGeneratedTool(argv, tool.name, params)
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