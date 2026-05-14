#!/usr/bin/env node

import chalk from 'chalk'
import ora from 'ora'
import yargs from 'yargs'
import { hideBin } from 'yargs/helpers'

import { getProjectIdOverride, buildCommandParams } from './cli-args.js'
import { config } from './config.js'
import { commands, executeToolCall } from './generated/commands.js'
import { createMCPContext, type AuthenticatedConfig, type Context } from './mcp-context.js'
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
        .strictCommands()
        .option('json', {
            type: 'boolean',
            describe: 'Output raw JSON without terminal formatting',
            default: false,
        })
        .option('project-id', {
            type: 'string',
            describe: 'PostHog project ID to use for this command instead of the stored project',
        })
        .demandCommand(1, 'You need at least one command before moving on')
        .fail((msg, err, yargs) => {
            if (err) throw err
            console.error(chalk.red(msg))
            console.error(yargs.help())
            process.exit(1)
        })
        .middleware(async (argv: any & { mcpContext?: Context }) => {
            // Skip setup for help/version/auth/livestream commands and bare command groups that show help.
            const isHelpCommand = argv.help || argv.h || argv._.includes('help')
            const isVersionCommand = argv.version || argv.v
            const isAuthCommand = argv._[0] === 'auth'
            const isLivestreamCommand = argv._[0] === 'livestream'
            const isCommandGroupHelpRequest = isTopLevelCommandGroupHelpRequest(argv)

            if (isHelpCommand || isVersionCommand || isAuthCommand || isLivestreamCommand || isCommandGroupHelpRequest) {
                return
            }

            const projectIdOverride = getProjectIdOverride(argv)
            const authConfig = await config.ensureAuth({ projectId: projectIdOverride })

            if ((!authConfig.accessToken && !authConfig.apiKey) || !authConfig.projectId || !authConfig.host) {
                console.error(chalk.red('Missing configuration. Run: ph auth login'))
                process.exit(1)
            }

            // Create context for API calls
            argv.mcpContext = createMCPContext(authConfig as AuthenticatedConfig)
        })

        // Auth commands
        .command(
            'auth',
            'Authentication commands',
            (yargs) => {
                const authCommands = yargs
                    .command('login', 'Login to PostHog with OAuth', {}, async () => {
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
            },
            () => {
                authCommandHelp?.() ?? cli.showHelp()
            }
        )

        // Livestream command (uses separate auth flow)
        .command(
            'livestream',
            'Stream live events (interactive TUI or JSON)',
            (yargs) => {
                return yargs
                    .option('token', { type: 'string', describe: 'JWT token (for scripting)' })
                    .option('host', { type: 'string', describe: 'PostHog host (default: https://app.posthog.com)' })
                    .option('livestream-host', { type: 'string', describe: 'Livestream service host (for self-hosted)' })
                    .option('event-type', { type: 'string', describe: 'Filter by event type(s), comma-separated' })
                    .option('distinct-id', { type: 'string', describe: 'Filter by distinct ID' })
                    .option('geo', { type: 'boolean', describe: 'Stream geo events instead' })
                    .option('json', { type: 'boolean', describe: 'Output JSON lines instead of interactive TUI' })
            },
            async (argv) => {
                const { runLivestream } = await import('./livestream/index.js')
                await runLivestream({
                    token: argv.token,
                    host: argv.host,
                    livestreamHost: argv.livestreamHost,
                    eventType: argv.eventType,
                    distinctId: argv.distinctId,
                    geo: argv.geo,
                })
            }
        )

    // Add human-readable commands from the new command mappings

    for (const [commandName, command] of Object.entries(commands)) {
        if (Object.keys(command.subcommands).length === 0) continue // Skip empty commands

        // Create the main command with aliases
        const commandAliases = command.aliases || []
        const commandSpec = [commandName, ...commandAliases]

        cli.command(
            commandSpec,
            command.description,
            (yargs) => {
                let subCommands = yargs.demandCommand(1, 'You need to specify a subcommand')

                // Add each subcommand
                for (const [subcommandName, subcommand] of Object.entries(command.subcommands)) {
                    const subcommandAliases = subcommand.aliases || []

                    // Check if this subcommand requires an ID
                    const requiresId = subcommand.endpoint && subcommand.endpoint.includes('{id}')

                    subCommands = subCommands.command(
                        [subcommandName, ...subcommandAliases],
                        subcommand.description,
                        (yargs) => {
                            return yargs
                                .option('id', {
                                    type: 'string',
                                    describe: 'Resource ID',
                                    demandOption: requiresId,
                                })
                                .strictOptions(false) // Allow additional API parameters
                        },
                        async (argv) => {
                            const params = buildCommandParams(argv)
                            await executeGeneratedTool(argv, subcommand.mcp_tool, params)
                        }
                    )
                }

                commandGroupHelp.set(commandName, () => subCommands.showHelp())
                return subCommands
            },
            () => {
                commandGroupHelp.get(commandName)?.() ?? cli.showHelp()
            }
        )
    }

    // Direct API access
    cli.command(
        'api <method> <path>',
        'Make direct API calls',
        {
            method: {
                type: 'string',
                describe: 'HTTP method',
                choices: ['GET', 'POST', 'PATCH', 'PUT', 'DELETE'],
            },
            path: { type: 'string', describe: 'API path' },
            body: { type: 'string', describe: 'Request body as JSON' },
            query: { type: 'string', describe: 'Query parameters as JSON' },
        },
        async (argv) => {
            const spinner = ora(`Making ${argv.method} request to ${argv.path}...`).start()

            try {
                const body = argv.body ? JSON.parse(argv.body) : undefined
                const query = argv.query ? JSON.parse(argv.query) : undefined

                const result = await (argv.mcpContext as Context).api.request({
                    method: argv.method as any,
                    path: argv.path!,
                    body,
                    query,
                })

                spinner.succeed('API call completed')
                printResult(argv, 'api', result)
            } catch (error: any) {
                spinner.fail('API call failed')
                console.error(chalk.red('Error:'), error.message)
                process.exit(1)
            }
        }
    )

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
