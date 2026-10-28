import { Command as Commander, CommanderError, Option } from 'commander'
import { parseArgs, type ParseArgsOptionsConfig } from 'node:util'

import { COMMANDS } from '@/commands'
import { resolveMode, type Mode, type OutputFormat } from '@/core/agent'
import {
    argumentSyntax,
    optionFlags,
    type Command,
    type CommandTree,
    type Group,
    type Legacy,
    type OptionSpec,
} from '@/core/command'
import { Context, GLOBAL_OPTIONS, type GlobalOptions } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { Output } from '@/core/output'
import type { Runtime } from '@/core/runtime'
import { kebabCase } from '@/core/text'
import { ApiError } from '@/posthog/api'
import { VERSION } from '@/version'

const ROOT_HELP = `
hog prints JSON when an agent such as Claude Code or Codex runs it, or when stdout is not a terminal.
Run \`hog auth login\` to log in, and \`hog commands -o json\` to list every command, its arguments and its options.`

const LEGACY_HELP_GROUP = 'Not ported yet (each one prints the posthog-cli command to run):'

function toOption(name: string, spec: OptionSpec): Option {
    const option = new Option(optionFlags(name, spec), spec.description)
    return spec.type === 'string' && spec.choices ? option.choices(spec.choices) : option
}

function helpText(command: Command): string {
    const sections = [
        command.notes,
        command.examples?.length ? `Examples:\n${command.examples.map((example) => `  ${example}`).join('\n')}` : '',
        command.scopes?.length ? `Needs a personal API key with: ${command.scopes.join(', ')}` : '',
    ]
    return sections
        .filter(Boolean)
        .map((section) => `\n${section}`)
        .join('\n')
}

const SHELL_SAFE_ARG = /^[\w@%+=:,./-]+$/

function shellQuote(arg: string): string {
    return SHELL_SAFE_ARG.test(arg) ? arg : `'${arg.replaceAll("'", "'\\''")}'`
}

function notPorted(path: string, legacy: Legacy, args: readonly string[]): HogError {
    const invocation = [legacy.use, ...args.map(shellQuote)].join(' ')
    return new HogError('not_ported', `\`hog ${path}\` isn't available yet. Run this instead:\n  ${invocation}`)
}

// A 403 names the scopes the command declares, which the API client doesn't know about.
function withScopeHint(error: unknown, scopes: readonly string[] | undefined): unknown {
    if (error instanceof ApiError && error.status === 403 && scopes?.length) {
        return error.withHint(
            `Check that the personal API key has the ${scopes.join(', ')} scope and access to this project.`
        )
    }
    return error
}

async function readArgument(runtime: Runtime, name: string, value: string): Promise<string> {
    const text = value === '-' ? await runtime.readStdin() : value
    if (!text.trim()) {
        throw new HogError(
            `empty_${name}`,
            `The ${name} is empty.`,
            `Pass the ${name} as an argument, or pipe it in with -.`
        )
    }
    return text
}

function createProgram(runtime: Runtime, mode: Mode, state: { exitCode: number }): Commander {
    const out = new Output(runtime, mode)

    function addRunnable(command: Commander, node: Command): void {
        const argEntries = Object.entries(node.args ?? {})
        for (const [name, spec] of argEntries) {
            command.argument(argumentSyntax(name, spec), spec.description)
        }
        for (const [name, spec] of Object.entries(node.options ?? {})) {
            command.addOption(toOption(name, spec))
        }
        const help = helpText(node)
        if (help) {
            command.addHelpText('after', help)
        }

        command.action(async (...params: unknown[]) => {
            const self = params.at(-1) as Commander
            const globals = self.optsWithGlobals() as GlobalOptions
            const options = self.opts()
            // Optional arguments stay undefined. The command's own types allow that, the tree's types don't.
            const args = {} as Record<string, string>
            for (const [index, [name, spec]] of argEntries.entries()) {
                const value = self.processedArgs[index] as string
                args[name] = spec.stdin && value !== undefined ? await readArgument(runtime, name, value) : value
            }

            const ctx = new Context(runtime, globals, mode, COMMANDS)
            let result: unknown
            try {
                result = await node.run({ args, options, ctx })
            } catch (error) {
                throw withScopeHint(error, node.scopes)
            }

            const render = mode.format === 'json' ? node.agent : node.human
            if (render && !globals.raw) {
                render({ result, out, args, options })
            } else if (result !== undefined) {
                out.json(result)
            }
            state.exitCode = node.exitCode?.(result) ?? 0
        })
    }

    function addNode(parent: Commander, name: string, node: Command | Group | Legacy, path: string): void {
        const command = parent.command(name).description(node.description)
        switch (node.kind) {
            case 'group':
                command.aliases(node.aliases ?? [])
                for (const [childName, child] of Object.entries(node.commands)) {
                    addNode(command, childName, child, `${path} ${childName}`)
                }
                return
            case 'legacy':
                command
                    .helpGroup(LEGACY_HELP_GROUP)
                    // `--help` reaches the action like any other argument, so it points to posthog-cli's help.
                    .helpOption(false)
                    .allowUnknownOption()
                    .allowExcessArguments()
                    .action((_options, self: Commander) => {
                        throw notPorted(path, node, self.args)
                    })
                return
            case 'command':
                addRunnable(command, node)
        }
    }

    const program = new Commander('hog')
        .description('The PostHog command line')
        .version(VERSION, '-V, --version', 'Show the version')
        .helpOption('-h, --help', 'Show help')
        // Listed in help only: run() turns `hog help <command...>` into `hog <command...> --help`.
        .helpCommand('help [command...]', 'Show help for a command')
        .configureOutput({
            writeOut: (text) => runtime.writeStdout(text),
            writeErr: (text) => runtime.writeStderr(text),
            // run() prints parse errors itself, in the caller's output format.
            outputError: () => {},
        })
        .exitOverride()
        .showSuggestionAfterError(true)
        .addHelpText('after', ROOT_HELP)
    for (const [name, spec] of Object.entries(GLOBAL_OPTIONS)) {
        program.addOption(toOption(name, spec))
    }
    for (const [name, node] of Object.entries(COMMANDS)) {
        addNode(program, name, node, name)
    }
    return program
}

const PRE_PARSE_OPTIONS: ParseArgsOptionsConfig = Object.fromEntries(
    Object.entries(GLOBAL_OPTIONS).map(([name, spec]) => [
        kebabCase(name),
        'short' in spec ? { type: spec.type, short: spec.short } : { type: spec.type },
    ])
)

// Reads the global options before commander runs, so hog knows the output format for errors
// raised while parsing, and where the command name starts.
function preParse(argv: readonly string[]): { format: OutputFormat | undefined; commandIndex: number | undefined } {
    const { values, tokens } = parseArgs({
        args: [...argv],
        options: PRE_PARSE_OPTIONS,
        strict: false,
        allowPositionals: true,
        tokens: true,
    })
    const output = values.output
    const format = GLOBAL_OPTIONS.output.choices.find((choice) => choice === output)
    return { format, commandIndex: tokens.find((token) => token.kind === 'positional')?.index }
}

// Full names of commands in groups whose last word is `name`, so `hog login` can point to `hog auth login`.
function nestedMatches(tree: CommandTree, name: string, prefix = ''): string[] {
    return Object.entries(tree).flatMap(([key, node]) => {
        const path = prefix ? `${prefix} ${key}` : key
        if (node.kind === 'group') {
            return nestedMatches(node.commands, name, path)
        }
        return prefix && key === name ? [path] : []
    })
}

function toHogError(caught: unknown): HogError {
    if (caught instanceof HogError) {
        return caught
    }
    if (caught instanceof CommanderError) {
        const message = caught.message.replace(/^error: /, '')
        const sentence = message.charAt(0).toUpperCase() + message.slice(1)
        if (caught.code === 'commander.unknownCommand') {
            const name = /unknown command '([^']+)'/.exec(caught.message)?.[1] ?? ''
            const [match] = nestedMatches(COMMANDS, name)
            const message = match ? `Unknown command '${name}'. Did you mean \`hog ${match}\`?` : sentence
            return new HogError(
                'unknown_command',
                message,
                'Run `hog --help` to see the available commands.',
                EXIT_USAGE
            )
        }
        return new HogError('usage_error', sentence, 'Run the command with --help to see its usage.', EXIT_USAGE)
    }
    return new HogError('internal_error', caught instanceof Error ? caught.message : String(caught))
}

export async function run(argv: readonly string[], runtime: Runtime): Promise<number> {
    const { format, commandIndex } = preParse(argv)
    const terminal = { isTTY: runtime.stdoutIsTTY, hasColors: runtime.stdoutHasColors, columns: runtime.stdoutColumns }
    const mode = resolveMode(runtime.env, terminal, format)
    const state = { exitCode: 0 }
    const program = createProgram(runtime, mode, state)
    if (argv.length === 0) {
        program.outputHelp()
        return 0
    }
    const args =
        commandIndex !== undefined && argv[commandIndex] === 'help'
            ? [...argv.slice(0, commandIndex), ...argv.slice(commandIndex + 1), '--help']
            : [...argv]

    try {
        await program.parseAsync(args, { from: 'user' })
        return state.exitCode
    } catch (caught) {
        if (caught instanceof CommanderError && caught.exitCode === 0) {
            return 0
        }
        const error = toHogError(caught)
        new Output(runtime, mode).error(error)
        return error.exitCode
    }
}
