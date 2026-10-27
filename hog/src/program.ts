import { Command, CommanderError, Option, type CommandUnknownOpts } from '@commander-js/extra-typings'

import pkg from '../package.json' with { type: 'json' }
import { resolveExecutionContext, type OutputFormat } from './agent'
import { COMMANDS, type CommandSpec } from './catalog'
import { registerQueryCommand } from './commands/query'
import { EXIT_USAGE, HogError } from './errors'
import { Printer } from './output'
import type { Runtime } from './runtime'

export interface GlobalOptions {
    host?: string
    dotenvFile?: string
    output?: OutputFormat
}

export interface CommandContext {
    runtime: Runtime
    globals: GlobalOptions
    printer: Printer
    userAgent: string
    setExitCode: (code: number) => void
}

const OUTPUT_FORMATS = ['text', 'json'] as const
const SHELL_SAFE_ARG = /^[\w@%+=:,./-]+$/

export function shellQuote(arg: string): string {
    return SHELL_SAFE_ARG.test(arg) ? arg : `'${arg.replaceAll("'", "'\\''")}'`
}

function notPorted(spec: CommandSpec, args: readonly string[]): HogError {
    const invocation = [spec.legacyCommand, ...args.map(shellQuote)].join(' ')
    return new HogError(
        'not_ported',
        `\`hog ${spec.name}\` isn't available yet. Run this instead:\n  ${invocation}`,
        undefined,
        1
    )
}

// Reads -o/--output before commander parses, so errors raised while parsing use the same format.
function requestedOutput(argv: readonly string[]): OutputFormat | undefined {
    for (let index = 0; index < argv.length; index++) {
        const arg = argv[index] ?? ''
        const inline = /^(?:-o|--output)=(.+)$/.exec(arg)?.[1]
        const value = inline ?? (arg === '-o' || arg === '--output' ? argv[index + 1] : undefined)
        if (value === 'text' || value === 'json') {
            return value
        }
    }
    return undefined
}

interface CommandManifestEntry {
    name: string
    summary: string
    available: boolean
    arguments?: { name: string; required: boolean; description: string }[]
    options?: { flags: string; description: string }[]
    use?: string
}

function describe(command: CommandUnknownOpts, prefix: string): CommandManifestEntry[] {
    const name = prefix ? `${prefix} ${command.name()}` : command.name()
    if (command.commands.length > 0) {
        return command.commands.flatMap((child) => describe(child, name))
    }
    return [
        {
            name,
            summary: command.description(),
            available: true,
            arguments: command.registeredArguments.map((argument) => ({
                name: argument.name(),
                required: argument.required,
                description: argument.description,
            })),
            options: command.options.map((option) => ({ flags: option.flags, description: option.description })),
        },
    ]
}

export function createProgram(runtime: Runtime, state: { exitCode: number }): Command {
    const program = new Command('hog')
        .description('The PostHog command line')
        .version(pkg.version, '-V, --version', 'Show the version')
        .option('--host <url>', 'The PostHog host to use instead of the one in your credentials')
        .option('--dotenv-file <path>', 'Read POSTHOG_CLI_* credentials from this file when the environment has none')
        .addOption(
            new Option('-o, --output <format>', 'Output format, json by default for agents and pipes').choices(
                OUTPUT_FORMATS
            )
        )
        .helpOption('-h, --help', 'Show help')
        .helpCommand(false)
        .configureOutput({
            writeOut: (text) => runtime.writeStdout(text),
            writeErr: (text) => runtime.writeStderr(text),
            // run() prints parse errors itself, in the caller's output format.
            outputError: () => {},
        })
        .exitOverride()
        .showSuggestionAfterError(true)
        .addHelpText(
            'after',
            '\nhog prints JSON when an agent such as Claude Code or Codex runs it, or when stdout is not a terminal.\nRun `hog commands -o json` to list every command, its arguments and its options.'
        )

    const contextFor = (command: CommandUnknownOpts): CommandContext => {
        const globals = command.optsWithGlobals() as GlobalOptions
        const execution = resolveExecutionContext(runtime.env, runtime.stdoutIsTTY, globals.output)
        return {
            runtime,
            globals,
            printer: new Printer(runtime, execution),
            userAgent: `hog/${pkg.version}`,
            setExitCode: (code) => {
                state.exitCode = code
            },
        }
    }

    registerQueryCommand(program, contextFor)

    for (const spec of COMMANDS.filter((candidate) => !candidate.available)) {
        program
            .command(spec.name)
            .description(spec.summary)
            .helpGroup('Not ported yet (each one prints the posthog-cli command to run):')
            .helpOption(false)
            .allowUnknownOption()
            .allowExcessArguments()
            .action((_options, command) => {
                throw notPorted(spec, command.args)
            })
    }

    program
        .command('commands')
        .description('List every command, for agents and scripts')
        .action((_options, command) => {
            const context = contextFor(command)
            const ported = program.commands.filter((child) =>
                COMMANDS.some((spec) => spec.available && spec.name === child.name())
            )
            const entries: CommandManifestEntry[] = [
                ...ported.flatMap((child) => describe(child, '')),
                ...COMMANDS.filter((spec) => !spec.available).map((spec) => ({
                    name: spec.name,
                    summary: spec.summary,
                    available: false,
                    use: spec.legacyCommand,
                })),
            ]
            if (context.printer.context.format === 'json') {
                const { agent, agentReason } = context.printer.context
                context.printer.json({
                    cli: 'hog',
                    version: pkg.version,
                    agent: agent ?? null,
                    agentReason,
                    commands: entries,
                })
                return
            }
            const width = Math.max(...entries.map((entry) => entry.name.length)) + 2
            for (const entry of entries) {
                const status = entry.available ? '' : context.printer.style(`  (use ${entry.use})`, 'dim')
                context.printer.line(`  ${entry.name.padEnd(width)}${entry.summary}${status}`)
            }
        })

    program
        .command('help')
        .description('Show help for a command')
        .argument('[command...]', 'The command to show help for')
        .action((names) => {
            const [first, ...rest] = names
            const spec = COMMANDS.find((candidate) => candidate.name === first)
            if (spec && !spec.available) {
                throw notPorted(spec, [...rest, '--help'])
            }
            let target: CommandUnknownOpts = program
            for (const name of names) {
                const child = target.commands.find((candidate) => candidate.name() === name)
                if (!child) {
                    throw new HogError(
                        'unknown_command',
                        `Unknown command: ${names.join(' ')}.`,
                        'Run `hog --help` to see the available commands.',
                        EXIT_USAGE
                    )
                }
                target = child
            }
            target.outputHelp()
        })

    return program
}

export async function run(argv: readonly string[], runtime: Runtime): Promise<number> {
    const state = { exitCode: 0 }
    const program = createProgram(runtime, state)
    const printer = new Printer(
        runtime,
        resolveExecutionContext(runtime.env, runtime.stdoutIsTTY, requestedOutput(argv))
    )

    if (argv.length === 0) {
        program.outputHelp()
        return 0
    }

    try {
        await program.parseAsync([...argv], { from: 'user' })
        return state.exitCode
    } catch (error) {
        if (error instanceof CommanderError) {
            if (error.exitCode === 0) {
                return 0
            }
            if (error.code === 'commander.unknownCommand') {
                const name = argv.find((arg) => !arg.startsWith('-')) ?? ''
                printer.error(
                    new HogError(
                        'unknown_command',
                        `Unknown command: ${name}.`,
                        'Run `hog --help` to see the available commands.',
                        EXIT_USAGE
                    )
                )
                return EXIT_USAGE
            }
            printer.error(
                new HogError(
                    'usage_error',
                    error.message.replace(/^error: /, ''),
                    'Run the command with --help to see its usage.',
                    EXIT_USAGE
                )
            )
            return EXIT_USAGE
        }
        if (error instanceof HogError) {
            printer.error(error)
            return error.exitCode
        }
        printer.error(new HogError('internal_error', error instanceof Error ? error.message : String(error)))
        return 1
    }
}
