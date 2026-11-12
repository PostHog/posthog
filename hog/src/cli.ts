import { Command as Commander, CommanderError, Option } from 'commander'
import { win32 } from 'node:path'
import { parseArgs, type ParseArgsOptionsConfig } from 'node:util'
import { z } from 'zod'

import { COMMANDS } from '@/commands'
import { resolveMode, type Mode, type OutputFormat } from '@/core/agent'
import { inCIWithoutAPerson } from '@/core/approval'
import {
    argumentSyntax,
    longFlag,
    optionFlags,
    parseOption,
    type Command,
    type CommandTree,
    type Group,
    type Legacy,
    type OptionSpec,
} from '@/core/command'
import { findConfig, loadConfig } from '@/core/config'
import { Context } from '@/core/context'
import { EXIT_FAILURE, EXIT_USAGE, HogError } from '@/core/errors'
import { DRY_RUN_ENV, envFlag, GLOBAL_OPTIONS, networkRuntime, optOutFlag, resolveGlobals } from '@/core/globals'
import { parseJsonOrUndefined } from '@/core/json'
import { Output } from '@/core/output'
import type { Runtime } from '@/core/runtime'
import { Telemetry } from '@/core/telemetry'
import { kebabCase } from '@/core/text'
import { ApiError } from '@/posthog/api'
import { resolveCredentials } from '@/posthog/credentials'
import { canStepUp, stepUpCommand, workloadScopesHint } from '@/posthog/scope-challenge'
import { UpdateCheck, updateChecksOff } from '@/upgrade/check'
import { VERSION } from '@/version'

const ROOT_HELP = `
hog prints JSON when an agent such as Claude Code or Codex runs it, or when stdout is not a terminal.
Run \`hog auth login\` to log in, and \`hog commands -o json\` to list every command, its arguments and its options.
HOG_DRY_RUN=1 turns on --dry-run for every command that has one, and fails the commands that would change something without it.
\`hog --version\` (or -V) prints the version.`

const LEGACY_HELP_GROUP = 'Not ported yet (each one prints the posthog-cli command to run):'

function toOption(name: string, spec: OptionSpec): Option {
    const sources = [
        spec.env?.length ? `env: ${spec.env.join(', ')}` : '',
        spec.config ? `posthog.json: ${spec.config}` : '',
    ]
        .filter(Boolean)
        .join('; ')
    const option = new Option(optionFlags(name, spec), sources ? `${spec.description} (${sources})` : spec.description)
    if (spec.type === 'string' && spec.multiple) {
        option.argParser((value: string, previous: string[] | undefined) => [...(previous ?? []), value])
    }
    return spec.type === 'string' && spec.choices ? option.choices(spec.choices) : option
}

function helpText(command: Command): string {
    const sections = [
        command.notes,
        command.examples?.length ? `Examples:\n${command.examples.map((example) => `  ${example}`).join('\n')}` : '',
        command.scopes?.length ? `Needs the scopes: ${command.scopes.join(', ')}` : '',
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

// posthog-cli takes --host and --dotenv-file before the subcommand only. Every other argument
// belongs to the legacy command, including an --output that names a path there.
const LEGACY_GLOBALS = new Set(['host', 'dotenv-file'])

function notPorted(argv: readonly string[], route: LegacyRoute): HogError {
    const globals: string[] = []
    const rest: string[] = []
    const skip = new Set(route.pathIndices)
    for (const token of route.tokens) {
        if (token.kind !== 'option') {
            continue
        }
        const beforePath = token.index < route.pathIndices[0]!
        if (LEGACY_GLOBALS.has(token.name) || beforePath) {
            skip.add(token.index)
            if (token.value !== undefined && !token.inlineValue) {
                skip.add(token.index + 1)
            }
            if (LEGACY_GLOBALS.has(token.name) && token.value !== undefined) {
                globals.push(`--${token.name}`, token.value)
            }
        }
    }
    argv.forEach((arg, index) => {
        if (!skip.has(index)) {
            rest.push(arg)
        }
    })
    const [binary, ...subcommand] = route.legacy.use.split(' ')
    const invocation = [binary, ...globals.map(shellQuote), ...subcommand, ...rest.map(shellQuote)].join(' ')
    return new HogError('not_ported', `\`hog ${route.path}\` isn't available yet. Run this instead:\n  ${invocation}`)
}

// A 403 without a step-up challenge names the scopes the command declares, which the API client doesn't know about.
async function withScopeHint(error: unknown, scopes: readonly string[] | undefined, ctx: Context): Promise<unknown> {
    if (!(error instanceof ApiError) || error.status !== 403 || error.code === 'step_up_required' || !scopes?.length) {
        return error
    }
    const credentials = await ctx.requestedCredentials?.catch(() => undefined)
    if (credentials?.source === 'workload') {
        return error.withHint(workloadScopesHint(scopes))
    }
    if (!canStepUp(credentials)) {
        return error.withHint(
            `Check that the personal API key has the ${scopes.join(', ')} scope and access to this project.`
        )
    }
    const { scopesNotCovered } = await import('@/posthog/scopes')
    const missing = scopesNotCovered(credentials?.key.status().scopes ?? [], scopes)
    return error.withHint(
        missing.length > 0
            ? `Run \`${stepUpCommand(missing, credentials?.key.host)}\` to add the scopes to your login, and check that you can access this project.`
            : 'Check that you can access this project.'
    )
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

interface RunState {
    exitCode: number
    noFail?: boolean
    debug?: boolean
    options?: string[]
    command?: string
    properties?: Record<string, unknown>
}

// commander reads `--no-fail` as turning off an option named `fail`, so `noFail` is set from it.
function negatedFlags(flags: Record<string, unknown>): Record<string, unknown> {
    const resolved = { ...flags }
    for (const name of Object.keys(GLOBAL_OPTIONS)) {
        const positive = /^no([A-Z].*)$/.exec(name)?.[1]
        if (positive) {
            const key = positive.charAt(0).toLowerCase() + positive.slice(1)
            resolved[name] = flags[key] === false ? true : undefined
        }
    }
    return resolved
}

// The flags the caller typed, by name. Values never leave, and neither does anything commander
// didn't parse as an option, such as a query that starts with dashes.
function usedOptions(command: Commander): string[] {
    const negated: Record<string, string> = { fail: 'no-fail', telemetry: 'no-telemetry' }
    return Object.keys(command.optsWithGlobals())
        .filter((key) => command.getOptionValueSourceWithGlobals(key) === 'cli')
        .map((key) => negated[key] ?? kebabCase(key))
        .sort()
}

function createProgram(runtime: Runtime, mode: Mode, state: RunState, telemetry: Telemetry): Commander {
    const out = new Output(runtime, mode)

    function addRunnable(command: Commander, node: Command, path: string): void {
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
            state.command = path
            telemetry.commandName = path.replaceAll(/[ -]/g, '_')
            state.options = usedOptions(self)
            const config = node.allowsInvalidConfig ? undefined : loadConfig(runtime)
            const globals = resolveGlobals(negatedFlags(self.optsWithGlobals()), runtime.env, (await config)?.config)
            state.noFail = globals.noFail === true
            state.debug = globals.debug === true
            if (globals.noTelemetry) {
                telemetry.disable()
            }
            let ctx: Context | undefined
            telemetry.credentials = () =>
                ctx?.requestedCredentials ??
                resolveCredentials({ ...runtime, writeStderr: () => {} }, { ...globals, envOnly: true })
            const commandRuntime = networkRuntime(runtime, globals)
            const options = self.opts()
            // An empty value, often an unset shell variable, fails here instead of falling back to a
            // default, such as the login's project.
            for (const [name, spec] of Object.entries(node.options ?? {})) {
                options[name] = parseOption(spec, options[name], longFlag(name), 'invalid_input')
            }
            if (envFlag(runtime.env, DRY_RUN_ENV)) {
                if (Object.hasOwn(node.options ?? {}, 'dryRun')) {
                    options.dryRun = true
                } else if (node.writes) {
                    throw new HogError(
                        'dry_run_unsupported',
                        `\`hog ${path}\` has no dry run, and HOG_DRY_RUN is set.`,
                        'Unset HOG_DRY_RUN to run it, or leave the command out of the dry run.',
                        EXIT_USAGE
                    )
                }
            }
            // Optional arguments stay undefined. The command's own types allow that, the tree's types don't.
            const args = {} as Record<string, string>
            for (const [index, [name, spec]] of argEntries.entries()) {
                const value = self.processedArgs[index] as string
                args[name] = spec.stdin && value !== undefined ? await readArgument(runtime, name, value) : value
            }

            ctx = new Context(commandRuntime, globals, mode, COMMANDS, config, telemetry)
            if (node.refusesCI && inCIWithoutAPerson(ctx)) {
                throw new HogError(
                    'not_in_ci',
                    `\`hog ${path}\` ${node.refusesCI.reason}, so it does not run in CI.`,
                    node.refusesCI.hint
                )
            }
            let result: unknown
            try {
                result = await node.run({ args, options, ctx })
            } catch (error) {
                throw await withScopeHint(error, node.scopes, ctx)
            }

            const render = mode.format === 'json' ? node.agent : node.human
            if (render && !globals.raw) {
                render({ result, out, args, options })
            } else if (result !== undefined) {
                out.json(globals.raw && node.raw ? node.raw(result) : result)
            }
            state.exitCode = node.exitCode?.(result) ?? 0
            state.properties = {
                dry_run: options.dryRun === true,
                ...node.telemetry?.({ result, args, options } as never),
            }
        })
    }

    function addNode(parent: Commander, name: string, node: Command | Group | Legacy, prefix = ''): void {
        const command = parent.command(name).description(node.description)
        const path = prefix ? `${prefix} ${name}` : name
        switch (node.kind) {
            case 'group':
                command.aliases(node.aliases ?? [])
                for (const [childName, child] of Object.entries(node.commands)) {
                    addNode(command, childName, child, path)
                }
                if (node.guide) {
                    addRunnable(command, node.guide, path)
                }
                return
            case 'legacy':
                // Listed in help only: run() answers a legacy command before commander parses it.
                command.helpGroup(LEGACY_HELP_GROUP)
                return
            case 'command':
                addRunnable(command, node, path)
        }
    }

    const program = new Commander('hog')
        .description('The PostHog command line')
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
        addNode(program, name, node)
    }
    return program
}

const PRE_PARSE_OPTIONS: ParseArgsOptionsConfig = Object.fromEntries(
    Object.entries(GLOBAL_OPTIONS).map(([name, spec]) => [
        kebabCase(name),
        'short' in spec ? { type: spec.type, short: spec.short } : { type: spec.type },
    ])
)

type Token = ReturnType<typeof parseArgs>['tokens'] extends (infer T)[] | undefined ? T : never

interface PreParsed {
    format: OutputFormat | undefined
    noFail: boolean
    noTelemetry: boolean
    tokens: Token[]
}

interface LegacyRoute {
    legacy: Legacy
    path: string
    pathIndices: number[]
    tokens: Token[]
}

// Reads the global options before commander runs, so hog knows the output format for errors
// raised while parsing, and where the command name starts.
function preParse(argv: readonly string[]): PreParsed {
    const { values, tokens } = parseArgs({
        args: [...argv],
        options: PRE_PARSE_OPTIONS,
        strict: false,
        allowPositionals: true,
        tokens: true,
    })
    const output = values.output
    const format = GLOBAL_OPTIONS.output.choices.find((choice) => choice === output)
    return { format, noFail: values['no-fail'] === true, noTelemetry: values['no-telemetry'] === true, tokens }
}

function findLegacy(tokens: Token[]): LegacyRoute | undefined {
    let tree: CommandTree = COMMANDS
    const names: string[] = []
    const pathIndices: number[] = []
    for (const token of tokens) {
        if (token.kind !== 'positional') {
            continue
        }
        const node: CommandTree[string] | undefined = Object.hasOwn(tree, token.value) ? tree[token.value] : undefined
        if (!node) {
            return undefined
        }
        names.push(token.value)
        pathIndices.push(token.index)
        if (node.kind === 'legacy') {
            return { legacy: node, path: names.join(' '), pathIndices, tokens }
        }
        if (node.kind === 'command') {
            return undefined
        }
        tree = node.commands
    }
    return undefined
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

// posthog-cli commands that hog groups under a new name, with the flags that changed.
const RENAMED: Record<string, { to: string; hint: string }> = {
    sourcemap: {
        to: 'error-tracking inject|upload|process',
        hint: 'Pass the folders as arguments instead of --directory, as in `hog error-tracking process dist`.',
    },
    hermes: {
        to: 'error-tracking inject|clone|upload',
        hint: 'Pass paths as arguments instead of --directory, and the two maps to `hog error-tracking clone` instead of -m and -c.',
    },
    dsym: {
        to: 'error-tracking upload',
        hint: 'Pass the folder as an argument instead of --directory, as in `hog error-tracking upload build/Release-iphoneos`.',
    },
    'symbol-sets': {
        to: 'error-tracking upload|download|extract',
        hint: 'Pass paths and the symbol set as arguments: `hog error-tracking download <id or ref>` replaces --id and --ref.',
    },
    release: {
        to: 'error-tracking release',
        hint: '`hog error-tracking release -o text` prints just the release ID, like `posthog-cli release resolve`.',
    },
    proguard: {
        to: 'error-tracking upload',
        hint: 'Pass the mapping as an argument instead of --path, as in `hog error-tracking upload mapping.txt --map-id <id>`.',
    },
    exp: {
        to: 'query|endpoints|schema',
        hint: 'The experimental commands are top level in hog, as in `hog endpoints pull` for `posthog-cli exp endpoints pull`.',
    },
    update: { to: 'upgrade', hint: 'Run `hog upgrade`.' },
    skill: {
        to: 'skills list|add',
        hint: '`hog skills list` lists the skills, and `hog skills add <skill...>` replaces `posthog-cli api skill install`.',
    },
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
            const renamed = RENAMED[name]
            if (renamed) {
                return new HogError(
                    'unknown_command',
                    `\`${name}\` is \`hog ${renamed.to}\` in hog.`,
                    renamed.hint,
                    EXIT_USAGE
                )
            }
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

const CliOptOuts = z.object({
    cli: z.object({ telemetry: z.unknown().optional(), updateCheck: z.unknown().optional() }),
})

// Read without the full schema, so an opt-out still counts in a file another check rejects. A file
// that isn't JSON stops the command later, with telemetry on.
async function configOptOuts(runtime: Runtime): Promise<{ telemetry: boolean; updateCheck: boolean }> {
    const none = { telemetry: false, updateCheck: false }
    const path = await findConfig(runtime)
    if (path === undefined) {
        return none
    }
    try {
        const cli = parseJsonOrUndefined(await runtime.readFile(path), CliOptOuts)?.cli
        return { telemetry: cli?.telemetry === false, updateCheck: cli?.updateCheck === false }
    } catch {
        return none
    }
}

// Windows can't replace a running hog.exe, so `hog upgrade` renamed it. It isn't running any more.
async function removeReplacedBinary(runtime: Runtime): Promise<void> {
    if (runtime.platform === 'win32' && !runtime.isDevelopment) {
        await runtime.removeFile(win32.join(win32.dirname(runtime.execPath), 'hog.old.exe')).catch(() => {})
    }
}

function safeEnvFlag(env: Runtime['env'], names: readonly string[]): boolean {
    try {
        return envFlag(env, names) === true
    } catch {
        return false
    }
}

// `$exception` frames for a bug, with file names only, so one bug groups together wherever hog is installed.
function stackFrames(error: unknown): Record<string, unknown>[] {
    const stack = error instanceof Error ? (error.stack ?? '') : ''
    return stack
        .split('\n')
        .slice(1)
        .map((line) => /at (?:(.+?) \()?(.+?):(\d+):(\d+)\)?$/.exec(line.trim()))
        .filter((match): match is RegExpExecArray => match !== null)
        .map(([, fn, file, line, column]) => ({
            platform: 'node:javascript',
            function: fn ?? '<anonymous>',
            filename: file!.split(/[\\/]/).at(-1),
            lineno: Number(line),
            colno: Number(column),
            in_app: !file!.includes('node_modules'),
        }))
        .reverse()
}

// Messages and hints can hold paths, setting values and API response text, so like posthog-cli the
// event carries only the error code, its HTTP details and, for a bug, the stack.
function captureFailure(telemetry: Telemetry, command: string | undefined, error: HogError, cause: unknown): void {
    const status = error instanceof ApiError ? error.status : undefined
    const bug = !(cause instanceof HogError)
    telemetry.capture('$exception', {
        $exception_list: [
            {
                type: bug && cause instanceof Error ? cause.name : error.code,
                value: error.code,
                mechanism: { type: 'generic', handled: !bug },
                ...(bug ? { stacktrace: { type: 'raw', frames: stackFrames(cause) } } : {}),
            },
        ],
        // A bug groups by its stack, so two different bugs in one command stay apart.
        ...(bug
            ? {}
            : { $exception_fingerprint: ['hog', command ?? 'unknown', error.code, status].filter(Boolean).join(':') }),
        error_code: error.code,
        http_status: status ?? null,
        api_error_type: error instanceof ApiError ? (error.type ?? null) : null,
    })
}

export async function run(argv: readonly string[], runtime: Runtime): Promise<number> {
    const { format, noFail, noTelemetry, tokens } = preParse(argv)
    const terminal = { isTTY: runtime.stdoutIsTTY, hasColors: runtime.stdoutHasColors, columns: runtime.stdoutColumns }
    const envFormat = GLOBAL_OPTIONS.output.choices.find((choice) => choice === runtime.env.HOG_OUTPUT)
    const mode = resolveMode(runtime.env, terminal, format ?? envFormat)
    const state: RunState = { exitCode: 0 }
    const optOuts = await configOptOuts(runtime)
    const telemetry = new Telemetry(
        runtime,
        mode,
        !(
            noTelemetry ||
            optOutFlag(runtime.env, GLOBAL_OPTIONS.noTelemetry.env) ||
            (runtime.telemetryToken !== undefined && optOuts.telemetry)
        )
    )
    const program = createProgram(runtime, mode, state, telemetry)
    if (argv.length === 0) {
        program.outputHelp()
        return 0
    }
    const started = runtime.now()
    const commandIndex = tokens.find((token) => token.kind === 'positional')?.index
    // Handled here rather than by commander, whose program-level --version would also catch
    // `hog upgrade --version <version>`.
    if (
        commandIndex === undefined &&
        tokens.some((token) => token.kind === 'option' && ['version', 'V'].includes(token.name))
    ) {
        runtime.writeStdout(`${VERSION}\n`)
        return 0
    }
    const isHelp = commandIndex !== undefined && argv[commandIndex] === 'help'
    const args = isHelp ? [...argv.slice(0, commandIndex), ...argv.slice(commandIndex + 1), '--help'] : [...argv]
    // Help and --version answer at once, so they don't wait for a request to finish.
    const answersAtOnce =
        isHelp || tokens.some((token) => token.kind === 'option' && ['help', 'h', 'version', 'V'].includes(token.name))
    const updates = answersAtOnce
        ? undefined
        : new UpdateCheck(runtime, optOuts.updateCheck || updateChecksOff(runtime, undefined))
    await removeReplacedBinary(runtime)

    let exitCode: number
    let failure: HogError | undefined
    try {
        const legacy = findLegacy(isHelp ? preParse(args).tokens : tokens)
        if (legacy) {
            state.command = legacy.path
            throw notPorted(args, legacy)
        }
        await program.parseAsync(args, { from: 'user' })
        // --no-fail also covers a result that reports a problem, like a failed push or a stale SDK.
        exitCode = state.noFail && state.exitCode === EXIT_FAILURE ? 0 : state.exitCode
    } catch (caught) {
        if (caught instanceof CommanderError && caught.exitCode === 0) {
            return 0
        }
        failure = toHogError(caught)
        new Output(runtime, mode).error(failure)
        if (failure.exitCode === EXIT_FAILURE && failure.code !== 'not_ported') {
            captureFailure(telemetry, state.command, failure, caught)
        }
        const ignore = state.noFail ?? (noFail || safeEnvFlag(runtime.env, GLOBAL_OPTIONS.noFail.env))
        exitCode = ignore && failure.exitCode === EXIT_FAILURE ? 0 : failure.exitCode
    }

    // A `hog_outdated` failure already says to update, so the notice would repeat it.
    if (failure?.code !== 'hog_outdated') {
        await updates?.finish({ mode, command: state.command })
    }

    // posthog-cli's usage event, so one dashboard covers both CLIs. Option names only, never values.
    telemetry.capture('posthog cli command run', {
        command_path: state.command ?? null,
        exit_code: exitCode,
        // Before --no-fail, so a push that reports failures still counts as one.
        success: failure === undefined && state.exitCode === 0,
        error_code: failure?.code ?? null,
        duration_ms: runtime.now() - started,
        options: state.options ?? [],
        ...state.properties,
    })
    await telemetry.flush(state.debug)
    return exitCode
}
