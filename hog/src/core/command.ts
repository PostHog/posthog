import type { Context } from './context'
import type { Output } from './output'
import { kebabCase } from './text'

export interface ArgumentSpec {
    description: string
    optional?: boolean
    // Collects every remaining argument into a list. Only the last argument can be variadic.
    variadic?: boolean
    // `-` reads the value from stdin, and an empty value is an error.
    stdin?: boolean
}

// `env` and `config` are for global options only: the env vars and the posthog.json key path, such
// as `cli.noFail`, that set them.
interface OptionSource {
    env?: readonly string[]
    config?: string
    // The posthog.json key means the opposite of the option, as `cli.telemetry: false` for --no-telemetry.
    negate?: boolean
    lenient?: boolean
}

export type OptionSpec =
    | ({ type: 'boolean'; description: string; short?: string } & OptionSource)
    | ({
          type: 'string'
          description: string
          short?: string
          // The name shown in help, as in `--host <url>`. Defaults to the option name.
          placeholder?: string
          choices?: readonly string[]
          // The option can repeat, as in `--var a=1 --var b=2`, and its value is a list.
          multiple?: boolean
      } & OptionSource)

type ArgumentValues<Args> = {
    [Name in keyof Args]: Args[Name] extends { variadic: true }
        ? string[]
        : Args[Name] extends { optional: true }
          ? string | undefined
          : string
}

export type OptionValues<Options> = {
    [Name in keyof Options]: Options[Name] extends { type: 'boolean' }
        ? boolean | undefined
        : Options[Name] extends { multiple: true }
          ? string[] | undefined
          : (Options[Name] extends { choices: readonly (infer Choice)[] } ? Choice : string) | undefined
}

interface CommandInput<Args, Options> {
    args: ArgumentValues<Args>
    options: OptionValues<Options>
}

interface RenderInput<Args, Options, Result> extends CommandInput<Args, Options> {
    result: Result
    out: Output
}

interface CommandDefinition<Args, Options, Result> {
    description: string
    args?: Args
    // The key becomes the flag: `dotenvFile` is `--dotenv-file`.
    options?: Options
    // The command changes something in PostHog or on disk. HOG_DRY_RUN turns on its `dryRun` option,
    // and fails it when it has none. Commands that only read run as usual in a dry run.
    writes?: boolean
    // The command runs when posthog.json is invalid, like `hog config check`, which reports why.
    // Every other command stops, so it never runs with settings hog couldn't read.
    allowsInvalidConfig?: boolean
    // Personal API key scopes the command needs. `hog commands` lists them, and a 403 names them.
    scopes?: readonly string[]
    notes?: string
    examples?: readonly string[]
    // Does the work and returns data. It never prints: `human` and `agent` decide how the data
    // looks. Import heavy dependencies here with `await import()`, so other commands don't load them.
    run(input: CommandInput<Args, Options> & { ctx: Context }): Promise<Result> | Result
    // What a person at a terminal sees. Defaults to the result as indented JSON.
    human?(input: RenderInput<Args, Options, Result>): void
    // What agents, pipes and `-o json` see. Defaults to the result as one line of JSON.
    agent?(input: RenderInput<Args, Options, Result>): void
    // Extra properties for the anonymous usage event: counts and names from the result, never
    // values, paths or text the caller typed.
    telemetry?(input: CommandInput<Args, Options> & { result: Result }): Record<string, unknown>
    // The exit code for a result. Defaults to 0. Failures throw a HogError instead.
    exitCode?(result: Result): number
}

// Methods, not function properties, so a command with specific arguments still fits `Command`.
export interface Command<
    Args extends Record<string, ArgumentSpec> = Record<string, ArgumentSpec>,
    Options extends Record<string, OptionSpec> = Record<string, OptionSpec>,
    Result = unknown,
> extends CommandDefinition<Args, Options, Result> {
    kind: 'command'
}

export interface Group {
    kind: 'group'
    description: string
    commands: CommandTree
    // Shorter names that work the same, like `et` for `error-tracking`. Help and agents use the full name.
    aliases?: readonly string[]
}

// A command posthog-cli still owns. hog lists it and points the caller to `use`, with the same arguments.
export interface Legacy {
    kind: 'legacy'
    description: string
    use: string
}

export type CommandTree = Readonly<Record<string, Command | Group | Legacy>>

export function defineCommand<
    const Args extends Record<string, ArgumentSpec> = {},
    const Options extends Record<string, OptionSpec> = {},
    Result = void,
>(definition: CommandDefinition<Args, Options, Result>): Command<Args, Options, Result> {
    return { kind: 'command', ...definition }
}

export function defineGroup(definition: Omit<Group, 'kind'>): Group {
    return { kind: 'group', ...definition }
}

export function defineLegacy(definition: Omit<Legacy, 'kind'>): Legacy {
    return { kind: 'legacy', ...definition }
}

export function optionFlags(name: string, spec: OptionSpec): string {
    const long = `--${kebabCase(name)}`
    const flag = spec.type === 'string' ? `${long} <${spec.placeholder ?? kebabCase(name)}>` : long
    return spec.short ? `-${spec.short}, ${flag}` : flag
}

export function argumentSyntax(name: string, spec: ArgumentSpec): string {
    const label = `${kebabCase(name)}${spec.variadic ? '...' : ''}`
    return spec.optional ? `[${label}]` : `<${label}>`
}
