import { VimMode } from 'monaco-vim'

import { VimrcCommand } from './vimrc'

export type VimMappingContext = 'normal' | 'insert' | 'visual'

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
}

function isMappingCommand({ command }: VimrcCommand): boolean {
    return command.split(/\s+/, 1)[0].endsWith('map')
}

export class VimrcMappingSession {
    private mappingCommands: string | null = null
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
        return commands
    }
}

export function createNonrecursiveVimMapping(lhs: string, rhs: string, context?: VimMappingContext): void {
    const Vim = (VimMode as unknown as { Vim: VimMappingApi }).Vim

    // Escape is handled before keymap lookup, so noremap cannot resolve it from the default keymap.
    if (context === 'insert' && rhs === '<Esc>') {
        Vim.mapCommand(lhs, 'action', 'exitInsertMode', {}, { context })
        return
    }

    const mappings: VimKeyMapping[] = []
    Vim.noremap.call({ _mapCommand: (mapping) => mappings.push(mapping) }, lhs, rhs, context)
    if (!mappings.length) {
        throw new Error(`Mapping "${lhs} ${rhs}" isn't supported by noremap. Use a map command for key sequences.`)
    }
    mappings.forEach((mapping) => Vim._mapCommand(mapping))
}
