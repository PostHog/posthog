import { Command as Commander, CommanderError, Option } from 'commander'
import { win32 } from 'node:path'
import { parseArgs, type ParseArgsOptionsConfig } from 'node:util'
import { z } from 'zod'

import { COMMANDS } from '@/commands'
import feedback from '@/commands/feedback'
import { SHORTCUTS } from '@/commands/shortcuts'
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
    type OptionSpec,
} from '@/core/command'
import { findConfig, loadConfig } from '@/core/config'
import { Context } from '@/core/context'
import {
    EXIT_CANCELLED,
    EXIT_CODES,
    EXIT_FAILURE,
    EXIT_SUCCESS,
    EXIT_USAGE,
    HogError,
    NO_FAIL_CODES,
} from '@/core/errors'
import { DRY_RUN_ENV, envFlag, GLOBAL_OPTIONS, networkRuntime, optOutFlag, resolveGlobals } from '@/core/globals'
import { parseJsonOrUndefined } from '@/core/json'
import { Output } from '@/core/output'
import { keptPath, type Runtime } from '@/core/runtime'
import { Telemetry } from '@/core/telemetry'
import { joinList, kebabCase } from '@/core/text'
import { checkWorker } from '@/error-tracking/worker'
import { ApiError } from '@/posthog/api'
import { resolveCredentials } from '@/posthog/credentials'
import { canStepUp, stepUpCommand, workloadScopesHint } from '@/posthog/scope-challenge'
import { UpdateCheck, updateChecksOff } from '@/updates/check'
import { shippedBinaries, targetFor } from '@/updates/targets'
import { VERSION } from '@/version'

const CODE_WIDTH = Math.max(...EXIT_CODES.map(({ code }) => String(code).length))

// What `hog` alone shows a person: the commands most people start with. `hog help` lists them all.
const OVERVIEW: readonly (readonly [heading: string, commands: readonly (readonly [string, string])[]])[] = [
    [
        'Get started',
        [
            ['setup', 'Add PostHog to the app in this folder'],
            ['auth login', 'Log in to PostHog'],
            ['whoami', 'Show who hog is logged in as'],
        ],
    ],
    [
        'Use PostHog',
        [
            ['query run <query>', 'Run a HogQL query'],
            ['api search <words...>', 'Find a PostHog API tool, then run it with hog api call'],
            ['et process [paths...]', 'Upload source maps and debug symbols after a build'],
            ['mcp add', "Connect PostHog's MCP server to your coding agent"],
            ['skills add <skill...>', 'Add PostHog skills for your coding agent'],
        ],
    ],
]

function overview(out: Output): string {
    const width = Math.max(...OVERVIEW.flatMap(([, commands]) => commands.map(([usage]) => usage.length))) + 6
    const sections = OVERVIEW.map(
        ([heading, commands]) =>
            `${out.style(heading, 'bold')}\n` +
            commands.map(([usage, text]) => `  ${out.style(`hog ${usage}`.padEnd(width), 'bold')}${text}`).join('\n')
    )
    return (
        [
            `hog ${VERSION}, the PostHog command line`,
            ...sections,
            `Run ${out.style('hog help', 'bold')} to see every command and option, or ${out.style('hog help <command>', 'bold')} for one command.`,
        ].join('\n\n') + '\n'
    )
}

// A person reads the help at a terminal, so it leaves out what only agents and scripts use.
const PEOPLE_HELP = `
Run \`hog help <command>\` for a command's options and examples, and \`hog --version\` for the version.`

const AGENT_HELP = `
hog prints JSON when an agent such as Claude Code or Codex runs it, or when stdout is not a terminal.
Run \`hog auth login\` to log in, and \`hog commands -o json\` to list every command, its arguments and its options.
HOG_DRY_RUN=1 turns on --dry-run for every command that has one, and fails the commands that would change something without it.
\`hog --version\` (or -V) prints the version.

Exit codes:
${EXIT_CODES.map(({ code, meaning }) => `  ${String(code).padEnd(CODE_WIDTH)}  ${meaning}`).join('\n')}
--no-fail turns ${joinList(NO_FAIL_CODES.map(String), 'and')} into ${EXIT_SUCCESS}.`

const UNFINISHED_CODES: ReadonlySet<number> = new Set(NO_FAIL_CODES)

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

async function readArgument(runtime: Runtime, name: string, value: string | string[]): Promise<string | string[]> {
    if (Array.isArray(value)) {
        return readListArgument(runtime, name, value)
    }
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

// A list takes one item per line, as posthog-cli's --stdin did, so a build plugin can pass more paths than
// a Windows command line holds.
async function readListArgument(runtime: Runtime, name: string, values: string[]): Promise<string[]> {
    if (!values.includes('-')) {
        return values
    }
    const lines = (await runtime.readStdin())
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => line !== '')
    if (lines.length === 0) {
        throw new HogError(
            `empty_${name}`,
            `stdin has no ${name}.`,
            `Pipe one per line, or pass the ${name} as arguments.`
        )
    }
    return [...values.filter((value) => value !== '-'), ...lines]
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
                const value = self.processedArgs[index] as string | string[] | undefined
                args[name] = (
                    spec.stdin && value !== undefined ? await readArgument(runtime, name, value) : value
                ) as string
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
            } finally {
                await ctx.close()
            }

            const render = mode.format === 'json' ? node.agent : node.human
            if (render && !globals.raw) {
                render({ result, out, args, options })
            } else if (result !== undefined) {
                out.json(globals.raw && node.raw ? node.raw(result) : result)
            }
            state.exitCode = node.exitCode?.(result) ?? EXIT_SUCCESS
            state.properties = {
                dry_run: options.dryRun === true,
                ...node.telemetry?.({ result, args, options } as never),
            }
        })
    }

    function addNode(parent: Commander, name: string, node: Command | Group, prefix = ''): void {
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
        .addHelpText('after', mode.format === 'json' ? AGENT_HELP : PEOPLE_HELP)
    for (const [name, spec] of Object.entries(GLOBAL_OPTIONS)) {
        program.addOption(toOption(name, spec))
    }
    for (const [name, node] of Object.entries(COMMANDS)) {
        addNode(program, name, node)
    }
    // Listed in help only: run() turns a shortcut into the command it names before commander parses.
    for (const [name, shortcut] of SHORTCUTS) {
        program.command(name).description(`${shortcut.description}, the same as hog ${shortcut.use}`)
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
    debug: boolean
    noFail: boolean
    noTelemetry: boolean
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
    return {
        format,
        debug: values.debug === true,
        noFail: values['no-fail'] === true,
        noTelemetry: values['no-telemetry'] === true,
        tokens,
    }
}

interface ResolvedRoute {
    // Names from the tree only, so arguments never reach the feedback hint.
    names: string[]
    node: Command | Group | undefined
}

function expandShortcut(argv: readonly string[]): string[] {
    const index = preParse(argv).tokens.find((token) => token.kind === 'positional')?.index
    const shortcut = index === undefined ? undefined : SHORTCUTS.get(argv[index]!)
    if (index === undefined || !shortcut) {
        return [...argv]
    }
    return [...argv.slice(0, index), ...shortcut.use.split(' '), ...argv.slice(index + 1)]
}

function resolveRoute(tokens: Token[]): ResolvedRoute {
    let tree: CommandTree = COMMANDS
    const route: ResolvedRoute = { names: [], node: undefined }
    for (const token of tokens) {
        if (token.kind !== 'positional') {
            continue
        }
        const entry = Object.entries(tree).find(
            ([name, node]) => name === token.value || (node.kind === 'group' && node.aliases?.includes(token.value))
        )
        if (!entry) {
            break
        }

        const [name, node] = entry
        route.names.push(name)
        route.node = node
        if (node.kind !== 'group') {
            break
        }
        tree = node.commands
    }
    return route
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

function feedbackCommand(route: ResolvedRoute, failure: HogError): string | undefined {
    if (route.node === feedback || failure.exitCode === EXIT_CANCELLED) {
        return undefined
    }
    const area = route.names.length > 0 ? `--area "hog ${route.names.join(' ')}" ` : ''
    return `hog feedback ${area}"<what happened>"`
}

// posthog-cli commands that hog groups under a new name, with the flags that changed. It helps people and
// agents move off posthog-cli, so delete it when posthog-cli stops working on 2027-02-27.
const RENAMED: Readonly<Record<string, { to: string; hint: string }>> = {
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
            // The name comes from the command line, so only RENAMED's own keys count, never `constructor`.
            const renamed = Object.hasOwn(RENAMED, name) ? RENAMED[name] : undefined
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
        const form = /option '(?:-\w, )?([^']+)' argument missing/.exec(caught.message)?.[1]
        if (caught.code === 'commander.optionMissingArgument' && form) {
            return new HogError(
                'usage_error',
                sentence,
                `Pass a value after the option, as in \`${form}\`.`,
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

function tlsOff(tokens: Token[], runtime: Runtime): boolean {
    return (
        tokens.some((token) => token.kind === 'option' && token.name === 'skip-ssl-verification') ||
        safeEnvFlag(runtime.env, GLOBAL_OPTIONS.skipSslVerification.env)
    )
}

// Windows can't replace a running exe, so `hog upgrade` renamed the ones it replaced. They aren't
// running any more.
async function removeReplacedBinary(runtime: Runtime): Promise<void> {
    const target = runtime.platform === 'win32' && !runtime.isDevelopment && targetFor('win32', runtime.arch, false)
    for (const name of target ? shippedBinaries(target) : []) {
        const replaced = keptPath(win32.join(win32.dirname(runtime.execPath), name), '', 'win32')
        await runtime.removeFile(replaced).catch(() => {})
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
    const { format, debug, noFail, noTelemetry, tokens } = preParse(argv)
    const terminal = { isTTY: runtime.stdoutIsTTY, hasColors: runtime.stdoutHasColors, columns: runtime.stdoutColumns }
    const envFormat = GLOBAL_OPTIONS.output.choices.find((choice) => choice === runtime.env.HOG_OUTPUT)
    const mode = resolveMode(runtime.env, terminal, format ?? envFormat)
    const state: RunState = { exitCode: EXIT_SUCCESS }
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
        if (mode.format === 'json') {
            program.outputHelp()
        } else {
            runtime.writeStdout(overview(new Output(runtime, mode)))
        }
        return EXIT_SUCCESS
    }
    const started = runtime.now()
    const commandIndex = tokens.find((token) => token.kind === 'positional')?.index
    // Not commander's --version, which would also catch `hog upgrade --version <version>`.
    if (
        commandIndex === undefined &&
        tokens.some((token) => token.kind === 'option' && ['version', 'V'].includes(token.name))
    ) {
        // The installers and the release workflow set this, to check what ships next to hog before they keep it.
        if (runtime.env.HOG_CHECK_INSTALL) {
            const failure = await checkWorker(runtime).catch((error: unknown) => error)
            if (failure) {
                runtime.writeStderr(`${failure instanceof HogError ? `${failure.message} ${failure.hint}` : failure}\n`)
                return EXIT_FAILURE
            }
        }
        runtime.writeStdout(`${VERSION}\n`)
        return EXIT_SUCCESS
    }
    const isHelp = commandIndex !== undefined && argv[commandIndex] === 'help'
    const args = expandShortcut(
        isHelp ? [...argv.slice(0, commandIndex), ...argv.slice(commandIndex + 1), '--help'] : argv
    )
    // Help and --version answer at once, so they don't wait for a request to finish.
    const answersAtOnce =
        isHelp || tokens.some((token) => token.kind === 'option' && ['help', 'h', 'version', 'V'].includes(token.name))
    const updates = answersAtOnce
        ? undefined
        : new UpdateCheck(
              runtime,
              optOuts.updateCheck || updateChecksOff(runtime, undefined) || tlsOff(tokens, runtime)
          )
    await removeReplacedBinary(runtime)

    const route = resolveRoute(preParse(args).tokens)
    let exitCode: number
    let failure: HogError | undefined
    try {
        await program.parseAsync(args, { from: 'user' })
        // --no-fail also covers a result that reports a problem, like a failed push or a stale SDK.
        exitCode = state.noFail && UNFINISHED_CODES.has(state.exitCode) ? EXIT_SUCCESS : state.exitCode
    } catch (caught) {
        if (caught instanceof CommanderError && caught.exitCode === EXIT_SUCCESS) {
            return EXIT_SUCCESS
        }
        failure = toHogError(caught)
        new Output(runtime, mode).error(failure, feedbackCommand(route, failure))
        if (UNFINISHED_CODES.has(failure.exitCode)) {
            captureFailure(telemetry, state.command, failure, caught)
        }
        const ignore = state.noFail ?? (noFail || safeEnvFlag(runtime.env, GLOBAL_OPTIONS.noFail.env))
        exitCode = ignore && UNFINISHED_CODES.has(failure.exitCode) ? EXIT_SUCCESS : failure.exitCode
    }

    // A `hog_outdated` failure already says to update, and a JSON failure is one object on stderr.
    if (failure?.code !== 'hog_outdated' && !(failure && mode.format === 'json')) {
        await updates?.finish({ mode, command: state.command })
    }

    // posthog-cli's usage event, so one dashboard covers both CLIs. Option names only, never values.
    telemetry.capture('posthog cli command run', {
        command_path: state.command ?? null,
        exit_code: exitCode,
        // Before --no-fail, so a push that reports failures still counts as one. A result that stops for
        // a person or leaves work running did what was asked, so it counts as a success.
        success: failure === undefined && state.exitCode !== EXIT_FAILURE,
        error_code: failure?.code ?? null,
        duration_ms: runtime.now() - started,
        options: state.options ?? [],
        ...state.properties,
    })
    // A run that failed before its command started has no state.debug, but --debug still applies.
    await telemetry.flush(state.debug ?? (debug || safeEnvFlag(runtime.env, GLOBAL_OPTIONS.debug.env)))
    return exitCode
}
