// The vimrc runs as ex commands against the live editor each time Vim mode starts. Only commands that
// configure Vim are allowed, because a command like `%d` or `g/x/d` would edit the user's query on every load.
const MAPPING_COMMANDS = ['map', 'nmap', 'imap', 'vmap', 'noremap', 'nnoremap', 'inoremap', 'vnoremap', 'unmap']
const OPTION_COMMANDS = ['set', 'setlocal', 'setglobal']
export const VIMRC_ALLOWED_COMMANDS: readonly string[] = [...MAPPING_COMMANDS, ...OPTION_COMMANDS, 'let']

// monaco-vim has no <Leader> key, so the parser replaces <Leader> with the key that `let mapleader` sets.
// Vim uses a backslash when no leader is set.
const DEFAULT_LEADER = '\\'
const MAPLEADER_PATTERN = /^let\s+(?:g:)?mapleader\s*=\s*(["'])(.*)\1$/
const LEADER_PATTERN = /<leader>/gi

function parseLeader(value: string): string | null {
    if (value === ' ' || /^\\<space>$/i.test(value)) {
        return '<Space>'
    }
    if (value === '\\\\') {
        return '\\'
    }
    return value.length === 1 && value.trim() ? value : null
}

export const VIMRC_MAX_LENGTH = 10000

export function mapsRunCommand({ command }: VimrcCommand): boolean {
    return /\s:run<cr>$/i.test(command)
}

export interface VimrcCommand {
    lineNumber: number
    command: string
}

export interface VimrcError {
    lineNumber: number
    message: string
}

export interface ParsedVimrc {
    commands: VimrcCommand[]
    errors: VimrcError[]
}

export function parseVimrc(vimrc: string): ParsedVimrc {
    const commands: VimrcCommand[] = []
    const errors: VimrcError[] = []
    let leader = DEFAULT_LEADER

    vimrc.split('\n').forEach((rawLine, index) => {
        const lineNumber = index + 1
        const rawCommand = rawLine.trim().replace(/^:+/, '')
        if (!rawCommand || rawCommand.startsWith('"')) {
            return
        }
        const commandName = rawCommand.match(/^[a-z]+(?=\s|$)/i)?.[0]
        if (!commandName || !VIMRC_ALLOWED_COMMANDS.includes(commandName)) {
            errors.push({
                lineNumber,
                message: `"${rawCommand}" isn't supported. Use one of: ${VIMRC_ALLOWED_COMMANDS.join(', ')}.`,
            })
            return
        }
        if (commandName === 'let') {
            const match = rawCommand.match(MAPLEADER_PATTERN)
            const nextLeader = match && parseLeader(match[2])
            if (!nextLeader) {
                errors.push({
                    lineNumber,
                    message: `"${rawCommand}" isn't supported. Use let only to set one leader key, for example let mapleader = " ".`,
                })
                return
            }
            leader = nextLeader
            return
        }
        const command = MAPPING_COMMANDS.includes(commandName)
            ? rawCommand.replace(LEADER_PATTERN, () => leader)
            : rawCommand
        const lhs = command.split(/\s+/)[1]
        if (MAPPING_COMMANDS.includes(commandName) && lhs?.startsWith(':') && lhs !== ':') {
            errors.push({
                lineNumber,
                message: `"${command}" maps an ex command. Map a key instead.`,
            })
            return
        }
        commands.push({ lineNumber, command })
    })

    return { commands, errors }
}
