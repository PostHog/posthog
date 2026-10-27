import pkg from '../package.json' with { type: 'json' }
import { COMMANDS } from './commands'

export interface Output {
    stdout: (text: string) => void
    stderr: (text: string) => void
}

const HELP_FLAGS = new Set(['-h', '--help', 'help'])
const VERSION_FLAGS = new Set(['-V', '--version'])

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
    const [first] = argv
    if (first === undefined || HELP_FLAGS.has(first)) {
        output.stdout(helpText())
        return 0
    }
    if (VERSION_FLAGS.has(first)) {
        output.stdout(pkg.version)
        return 0
    }

    const command = COMMANDS.find((candidate) => candidate.name === first)
    if (!command) {
        output.stderr(`Unknown command: ${first}. Run \`hog --help\` to see the available commands.`)
        return 1
    }
    output.stderr(`\`hog ${command.name}\` isn't available yet. Use \`${command.legacyCommand}\` until it is.`)
    return 1
}
