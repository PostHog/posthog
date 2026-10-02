import { VimMode } from 'monaco-vim'

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
    mapCommand: (
        keys: string,
        type: string,
        name: string,
        args: Record<string, unknown>,
        extra: { context: VimMappingContext }
    ) => void
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
