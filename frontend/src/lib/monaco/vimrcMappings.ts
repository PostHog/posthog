import { VimMode } from 'monaco-vim'

import { VimrcCommand } from './vimrc'

export type VimMappingContext = 'normal' | 'insert' | 'visual'
type CommandModeContext = Exclude<VimMappingContext, 'insert'>

export const RUN_QUERY_ACTION = 'runPostHogQuery'
const RUN_QUERY_RHS = /^:run<cr>$/i

interface VimKeyMapping {
    keys: string
    type: string
    [key: string]: unknown
}

interface VimMappingApi {
    noremap: (
        this: { _mapCommand: (mapping: VimKeyMapping) => void },
        lhs: string,
        rhs: string,
        context?: VimMappingContext
    ) => void
    _mapCommand: (mapping: VimKeyMapping) => void
    mapclear: () => void
    mapCommand: (
        keys: string,
        type: string,
        name: string,
        args: Record<string, unknown>,
        extra: { context: VimMappingContext }
    ) => void
    findKey: (this: unknown, cm: any, key: string, origin?: string) => unknown
    maybeInitVimState_: (cm: any) => {
        insertMode: boolean
        visualMode: boolean
        inputState: { keyBuffer: string; operator: string | null }
    }
}

const VIM_KEY_PATTERN = /<\w+-.+?>|<\w+>|./g

function isMappingCommand({ command }: VimrcCommand): boolean {
    return command.split(/\s+/, 1)[0].endsWith('map')
}

const MAPPING_CONTEXTS: Record<string, CommandModeContext[]> = {
    map: ['normal', 'visual'],
    noremap: ['normal', 'visual'],
    nmap: ['normal'],
    nnoremap: ['normal'],
    vmap: ['visual'],
    vnoremap: ['visual'],
}

function getMappingPrefixes(commands: VimrcCommand[]): Record<CommandModeContext, Set<string>> {
    const prefixes: Record<CommandModeContext, Set<string>> = { normal: new Set(), visual: new Set() }
    for (const { command } of commands) {
        const [commandName, lhs = ''] = command.split(/\s+/)
        const keys = lhs.match(VIM_KEY_PATTERN) ?? []
        for (const context of MAPPING_CONTEXTS[commandName] ?? []) {
            for (let length = 1; length < keys.length; length++) {
                prefixes[context].add(keys.slice(0, length).join(''))
            }
        }
    }
    return prefixes
}

export class VimrcMappingSession {
    private mappingCommands: string | null = null
    private mappingPrefixes = getMappingPrefixes([])
    private editorCount = 0

    retainEditor(): () => void {
        this.editorCount++
        let released = false
        return () => {
            if (released) {
                return
            }
            released = true
            this.editorCount--
            if (!this.editorCount) {
                this.mappingCommands = null
            }
        }
    }

    getCommandsToApply(commands: VimrcCommand[]): VimrcCommand[] {
        const mappingCommands = commands
            .filter(isMappingCommand)
            .map(({ command }) => command)
            .join('\n')
        // Replaying the same profile would erase mappings typed in another active editor.
        if (mappingCommands === this.mappingCommands) {
            return commands.filter((command) => !isMappingCommand(command))
        }
        const Vim = (VimMode as unknown as { Vim: VimMappingApi }).Vim
        Vim.mapclear()
        this.mappingCommands = mappingCommands
        this.mappingPrefixes = getMappingPrefixes(commands.filter(isMappingCommand))
        return commands
    }

    isMappingPrefix(keys: string, context: CommandModeContext): boolean {
        return this.mappingPrefixes[context].has(keys)
    }
}

// monaco-vim runs a full key match at once, so a built-in key such as <Space> or "," runs before the user
// can type the rest of a mapping like <Space>r. This patch keeps a vimrc mapping prefix pending instead.
// As with Vim's `notimeout`, the built-in command of that key no longer runs on its own.
export function holdVimrcMappingPrefixes(session: VimrcMappingSession): void {
    const Vim = (VimMode as unknown as { Vim: VimMappingApi }).Vim
    const originalFindKey = Vim.findKey

    Vim.findKey = function (cm, key, origin) {
        const vim = Vim.maybeInitVimState_(cm)
        if (!vim.insertMode && !vim.inputState.operator) {
            const keys = vim.inputState.keyBuffer + key
            if (session.isMappingPrefix(keys, vim.visualMode ? 'visual' : 'normal')) {
                vim.inputState.keyBuffer = keys
                return () => true
            }
        }
        return originalFindKey.call(this, cm, key, origin)
    }
}

export function createNonrecursiveVimMapping(lhs: string, rhs: string, context?: VimMappingContext): void {
    const Vim = (VimMode as unknown as { Vim: VimMappingApi }).Vim

    // Escape is handled before keymap lookup, so noremap cannot resolve it from the default keymap.
    if (context === 'insert' && rhs === '<Esc>') {
        Vim.mapCommand(lhs, 'action', 'exitInsertMode', {}, { context })
        return
    }

    // A key-to-ex mapping leaves visual mode before the ex command runs, which loses the selection.
    // An action runs while the selection is still active, so a visual mapping runs only the selected text.
    if (RUN_QUERY_RHS.test(rhs)) {
        if (context === 'insert') {
            throw new Error(`Mapping "${lhs} ${rhs}" isn't supported in insert mode. Use nnoremap or vnoremap.`)
        }
        const contexts: VimMappingContext[] = context ? [context] : ['normal', 'visual']
        contexts.forEach((mappingContext) =>
            Vim.mapCommand(lhs, 'action', RUN_QUERY_ACTION, {}, { context: mappingContext })
        )
        return
    }

    const mappings: VimKeyMapping[] = []
    Vim.noremap.call({ _mapCommand: (mapping) => mappings.push(mapping) }, lhs, rhs, context)
    if (!mappings.length) {
        throw new Error(`Mapping "${lhs} ${rhs}" isn't supported by noremap. Use a map command for key sequences.`)
    }
    mappings.forEach((mapping) => Vim._mapCommand(mapping))
}
