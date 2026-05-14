#!/usr/bin/env node

import chalk from 'chalk'
import ora from 'ora'
import yargs from 'yargs'
import { hideBin } from 'yargs/helpers'

import { getProjectIdOverride, buildCommandParams } from './cli-args.js'
import { config } from './config.js'
import { commands, executeToolCall } from './generated/commands.js'
import { CHARTABLE_INSIGHT_TOOLS } from './insight-display.js'
import { createMCPContext, type AuthenticatedConfig, type Context } from './mcp-context.js'
import { openBrowser } from './oauth.js'
import { printResult } from './output.js'

const GLOBAL_PATH_PARAMS = new Set(['project_id', 'org_id'])

function getResourcePathParams(endpoint: string | undefined): string[] {
    return Array.from(endpoint?.matchAll(/\{([^}]+)\}/g) ?? [])
        .map((match) => match[1])
        .filter((param) => !GLOBAL_PATH_PARAMS.has(param))
}

function pathParamOptionName(param: string): string {
    return param.replace(/_/g, '-')
}

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
        .usage('Work with PostHog from the command line.\n\n$0 <command> [options]')
        .help()
        .alias('h', 'help')
        .version('0.1.0')
        .wrap(120)
        .strictCommands()
        .option('json', {
            type: 'boolean',
            describe: 'Output JSON (syntax-highlighted in a TTY, plain when piped)',
            default: false,
        })
        .option('jq', {
            type: 'string',
            describe: 'Filter JSON output using a jq expression (requires --json; same TTY-aware highlighting)',
        })
        .option('project-id', {
            type: 'string',
            describe: 'PostHog project ID to use for this command instead of the stored project',
        })
        .check((argv) => {
            if (argv.jq !== undefined && !argv.json) {
                throw new Error('--jq requires --json')
            }
            return true
        })
        .demandCommand(1, 'NO_COMMAND')
        .fail((msg, err, yargs) => {
            if (err) throw err
            // Bare invocations (`ph`, `ph insights`) should print help and exit 0,
            // matching `gh`'s friendly behavior instead of treating it as a usage error.
            if (msg === 'NO_COMMAND' || msg === 'NO_SUBCOMMAND') {
                yargs.showHelp('log')
                process.exit(0)
            }
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

            if (
                isHelpCommand ||
                isVersionCommand ||
                isAuthCommand ||
                isLivestreamCommand ||
                isCommandGroupHelpRequest
            ) {
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
                    .option('livestream-host', {
                        type: 'string',
                        describe: 'Livestream service host (for self-hosted)',
                    })
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
                    json: argv.json,
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
                let subCommands = yargs.demandCommand(1, 'NO_SUBCOMMAND')

                // Add each subcommand
                for (const [subcommandName, subcommand] of Object.entries(command.subcommands)) {
                    const subcommandAliases = subcommand.aliases || []

                    const pathParams = getResourcePathParams(subcommand.endpoint)
                    const idAliasDescription =
                        pathParams.length === 1 && pathParams[0] !== 'id'
                            ? `Alias for --${pathParamOptionName(pathParams[0])}`
                            : 'Resource ID'

                    subCommands = subCommands.command(
                        [subcommandName, ...subcommandAliases],
                        subcommand.description,
                        (yargs) => {
                            let yargsBuilder = yargs.option('id', {
                                type: 'string',
                                describe: idAliasDescription,
                            })

                            for (const pathParam of pathParams) {
                                if (pathParam === 'id') {
                                    continue
                                }
                                yargsBuilder = yargsBuilder.option(pathParamOptionName(pathParam), {
                                    type: 'string',
                                    describe: `Path parameter: ${pathParam}`,
                                })
                            }

                            // Add options from inputs definition
                            if (subcommand.inputs && subcommand.inputs.properties) {
                                for (const [paramName, paramDef] of Object.entries(
                                    subcommand.inputs.properties as Record<string, any>
                                )) {
                                    yargsBuilder = yargsBuilder.option(paramName, {
                                        type:
                                            paramDef.type === 'number'
                                                ? 'number'
                                                : paramDef.type === 'boolean'
                                                  ? 'boolean'
                                                  : 'string',
                                        describe: paramDef.description,
                                        default: paramDef.default,
                                    })
                                }
                            }

                            // Add --web option for view commands
                            if (subcommandName === 'view' && subcommand.method === 'GET') {
                                yargsBuilder = yargsBuilder.option('web', {
                                    type: 'boolean',
                                    describe: 'Open the resource in your browser instead of showing JSON',
                                    default: false,
                                })
                            }
                            return yargsBuilder.strictOptions(false) // Allow additional API parameters
                        },
                        async (argv) => {
                            const params = buildCommandParams(argv)
                            // The bare GET only returns insight metadata, so for chart-rendering
                            // tools we default to a blocking refresh — users can still override
                            // with `--refresh async`. Tool list lives in CHARTABLE_INSIGHT_TOOLS.
                            if (CHARTABLE_INSIGHT_TOOLS.has(subcommand.mcp_tool) && params.refresh === undefined) {
                                params.refresh = 'blocking'
                            }

                            // Handle --web option for view commands
                            if (argv.web && subcommandName === 'view' && subcommand.method === 'GET') {
                                await executeViewCommandWithWeb(argv, subcommand.mcp_tool, params)
                            } else {
                                await executeGeneratedTool(argv, subcommand.mcp_tool, params)
                            }
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
                await printResult(argv, 'api', result)
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
    try {
        const result = await executeToolCall(argv.mcpContext as Context, toolName, params)
        await printResult(argv, toolName, result)
    } catch (error: any) {
        console.error(chalk.red('Error:'), error.message)
        process.exit(1)
    }
}

async function executeViewCommandWithWeb(argv: any, toolName: string, params: any) {
    try {
        // Construct PostHog URL directly without API call
        const url = await constructPostHogUrl(argv.mcpContext as Context, toolName, null, params)

        if (!url) {
            console.error(chalk.red('Error: Could not determine PostHog URL for this resource'))
            // Fall back to normal execution with API call
            await executeGeneratedTool(argv, toolName, params)
            return
        }

        // Open URL in browser
        openBrowser(url)
        console.log(chalk.green(`Opened in browser: ${url}`))
    } catch (error: any) {
        console.error(chalk.red('Error:'), error.message)
        process.exit(1)
    }
}

async function constructPostHogUrl(
    context: Context,
    toolName: string,
    result: any,
    params: any
): Promise<string | undefined> {
    const projectId = await context.stateManager.getProjectId()

    // Extract host from the API client config
    const baseUrl = (context.api as any).config.baseUrl

    if (!baseUrl || !projectId) {
        return undefined
    }

    // Map tool names to PostHog paths
    const resourceId = params.id || result?.id

    if (!resourceId) {
        return undefined
    }

    const urlMappings: Record<string, string> = {
        'feature-flag-get-definition': `/project/${projectId}/feature_flags/${resourceId}`,
        'insight-get': `/project/${projectId}/insights/${resourceId}`,
        'experiment-get': `/project/${projectId}/experiments/${resourceId}`,
        'cohorts-retrieve': `/project/${projectId}/cohorts/${resourceId}`,
        'dashboard-get': `/project/${projectId}/dashboard/${resourceId}`,
        'survey-get': `/project/${projectId}/surveys/${resourceId}`,
        'notebook-get': `/project/${projectId}/notebooks/${resourceId}`,
    }

    const path = urlMappings[toolName]
    if (path) {
        return `${baseUrl}${path}`
    }

    return undefined
}

main().catch((err) => {
    console.error(chalk.red(err instanceof Error ? err.message : String(err)))
    process.exit(1)
})
