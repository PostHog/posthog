// The vimrc runs as ex commands against the live editor each time Vim mode starts. Only commands that
// configure Vim are allowed, because a command like `%d` or `g/x/d` would edit the user's query on every load.
const MAPPING_COMMANDS = ['map', 'nmap', 'imap', 'vmap', 'noremap', 'nnoremap', 'inoremap', 'vnoremap', 'unmap']
const OPTION_COMMANDS = ['set', 'setlocal', 'setglobal']
export const VIMRC_ALLOWED_COMMANDS: readonly string[] = [...MAPPING_COMMANDS, ...OPTION_COMMANDS]

export const VIMRC_MAX_LENGTH = 10000

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

    vimrc.split('\n').forEach((rawLine, index) => {
        const lineNumber = index + 1
        const command = rawLine.trim().replace(/^:+/, '')
        if (!command || command.startsWith('"')) {
            return
        }
        const commandName = command.match(/^[a-z]+/i)?.[0]
        if (!commandName || !VIMRC_ALLOWED_COMMANDS.includes(commandName)) {
            errors.push({
                lineNumber,
                message: `"${command}" isn't supported. Use one of: ${VIMRC_ALLOWED_COMMANDS.join(', ')}.`,
            })
            return
        }
        commands.push({ lineNumber, command })
    })

    return { commands, errors }
}
