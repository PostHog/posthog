import pkg from '../package.json' with { type: 'json' }
import { COMMANDS } from './commands'

export interface Output {
    stdout: (text: string) => void
    stderr: (text: string) => void
}

const HELP_FLAGS = new Set(['-h', '--help', 'help'])
const VERSION_FLAGS = new Set(['-V', '--version'])
const SHELL_SAFE_ARG = /^[\w@%+=:,./-]+$/

export function shellQuote(arg: string): string {
    return SHELL_SAFE_ARG.test(arg) ? arg : `'${arg.replaceAll("'", "'\\''")}'`
}

export function helpText(): string {
    const width = Math.max(...COMMANDS.map((command) => command.name.length)) + 2
    const commandLines = COMMANDS.map((command) => `  ${command.name.padEnd(width)}${command.summary}`)
    return [
        `hog ${pkg.version}`,
        'The PostHog command line',
        '',
        'Usage: hog <command> [options]',
        '',
        'Commands:',
        ...commandLines,
        '',
        'Options:',
        '  -h, --help     Show this help',
        '  -V, --version  Show the version',
    ].join('\n')
}

export function run(argv: readonly string[], output: Output): number {
    const [first, ...rest] = argv
    const [helpTarget, ...helpRest] = rest
    if (first === undefined || (HELP_FLAGS.has(first) && helpTarget === undefined)) {
        output.stdout(helpText())
        return 0
    }
    if (VERSION_FLAGS.has(first)) {
        output.stdout(pkg.version)
        return 0
    }

    // `hog help <command>` asks for that command's own help, which only posthog-cli has today.
    const name = first === 'help' && helpTarget !== undefined ? helpTarget : first
    const args = first === 'help' && helpTarget !== undefined ? [...helpRest, '--help'] : rest
    const command = COMMANDS.find((candidate) => candidate.name === name)
    if (!command) {
        output.stderr(`Unknown command: ${name}. Run \`hog --help\` to see the available commands.`)
        return 1
    }
    const legacyInvocation = [command.legacyCommand, ...args.map(shellQuote)].join(' ')
    output.stderr(`\`hog ${command.name}\` isn't available yet. Run this instead:\n  ${legacyInvocation}`)
    return 1
}
