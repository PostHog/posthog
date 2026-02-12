import { VimMode } from 'monaco-vim'

// Vim clipboard integration — syncs vim yank/delete registers with the system clipboard
// (equivalent to `set clipboard=unnamed` in vim)
let vimClipboardCache = ''
let vimClipboardRegistersInitialized = false

const vimClipboardRegister = {
    setText(text: string): void {
        vimClipboardCache = text || ''
        void navigator.clipboard?.writeText(vimClipboardCache)
    },
    pushText(text: string, linewise: boolean): void {
        if (linewise && vimClipboardCache.length > 0 && !vimClipboardCache.endsWith('\n')) {
            vimClipboardCache += '\n'
        }
        vimClipboardCache += text
        void navigator.clipboard?.writeText(vimClipboardCache)
    },
    clear(): void {
        vimClipboardCache = ''
    },
    toString(): string {
        return vimClipboardCache
    },
}

export function setupVimClipboardSync(vimAdapter: VimMode): () => void {
    if (!vimClipboardRegistersInitialized) {
        try {
            ;(VimMode as any).Vim.defineRegister('*', vimClipboardRegister)
            ;(VimMode as any).Vim.defineRegister('+', vimClipboardRegister)
        } catch {
            // Already registered (e.g. hot module reload)
        }
        vimClipboardRegistersInitialized = true
    }

    const syncToClipboard = (): void => {
        const content = (VimMode as any).Vim.getRegisterController().getRegister('"').toString()
        if (content) {
            void navigator.clipboard?.writeText(content)
        }
    }
    vimAdapter.on('vim-command-done', syncToClipboard)

    const editorDomNode = (vimAdapter as any).editor?.getDomNode?.() as HTMLElement | null
    const updateCacheOnFocus = (): void => {
        void navigator.clipboard
            ?.readText()
            .then((text: string) => {
                vimClipboardCache = text
            })
            .catch(() => {})
    }
    editorDomNode?.addEventListener('focusin', updateCacheOnFocus)

    return () => {
        vimAdapter.off('vim-command-done', syncToClipboard)
        editorDomNode?.removeEventListener('focusin', updateCacheOnFocus)
    }
}
