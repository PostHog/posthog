import { editor as monacoEditor } from 'monaco-editor'
import { VimMode, initVimMode } from 'monaco-vim'

interface VimModeHandle {
    vimMode: VimMode
    dispose: () => void
}

function extractPatternBeforeSeparator(str: string, separator: string): string | null {
    let result = ''
    for (let i = 0; i < str.length; i++) {
        if (str[i] === '\\' && i + 1 < str.length) {
            result += str[i] + str[i + 1]
            i++
        } else if (str[i] === separator) {
            return result
        } else {
            result += str[i]
        }
    }
    return result
}

function patchAddOverlay(cmAdapter: any): () => void {
    const original = cmAdapter.addOverlay.bind(cmAdapter)

    cmAdapter.addOverlay = function ({ query }: { query: RegExp }): void {
        if (!query) {
            return
        }
        let matchCase = false
        let isRegex = false
        let source: string

        if (query instanceof RegExp) {
            isRegex = true
            matchCase = !query.ignoreCase
            source = query.source
        } else {
            source = String(query)
        }

        const model = this.editor.getModel()
        if (!model) {
            return
        }

        const allMatches = model.findMatches(source, false, isRegex, matchCase, null, false) as any[]
        if (!allMatches?.length) {
            this.removeOverlay()
            return
        }
        this.highlightRanges(allMatches.map((m: any) => m.range))
    }

    return () => {
        cmAdapter.addOverlay = original
    }
}

function patchSubstituteHighlight(cmAdapter: any, statusBar: any): () => void {
    const originalSetSec = statusBar.setSec.bind(statusBar)
    const substituteRegex = /s([^\w\s])(.*)/

    let hasSubstituteHighlight = false

    statusBar.setSec = function (text: string, callback: any, options: any): any {
        if (!text && hasSubstituteHighlight) {
            cmAdapter.removeOverlay()
            hasSubstituteHighlight = false
        }
        if (options && !options.onKeyInput) {
            options.onKeyInput = (_event: InputEvent, value: string): void => {
                const match = value.match(substituteRegex)
                if (match) {
                    const pattern = extractPatternBeforeSeparator(match[2], match[1])
                    if (pattern) {
                        try {
                            cmAdapter.addOverlay({ query: new RegExp(pattern, 'gim') })
                            hasSubstituteHighlight = true
                            return
                        } catch {
                            // invalid regex in progress
                        }
                    }
                }
                if (hasSubstituteHighlight) {
                    cmAdapter.removeOverlay()
                    hasSubstituteHighlight = false
                }
            }
        }
        return originalSetSec(text, callback, options)
    }

    return () => {
        statusBar.setSec = originalSetSec
    }
}

function setupClipboardSync(editor: monacoEditor.IStandaloneCodeEditor, statusBarEl: HTMLElement): () => void {
    const regController = (VimMode as any).Vim.getRegisterController()
    const origPushText = regController.pushText.bind(regController)
    const cleanups: (() => void)[] = []

    regController.pushText = function (
        registerName: string,
        operator: string,
        text: string,
        linewise: boolean,
        blockwise: boolean
    ): void {
        origPushText(registerName, operator, text, linewise, blockwise)
        if (text) {
            void navigator.clipboard.writeText(text).catch(() => {})
        }
    }

    let lastStatusBarBlurTime = 0
    const onStatusBarFocusOut = (): void => {
        lastStatusBarBlurTime = Date.now()
    }
    statusBarEl.addEventListener('focusout', onStatusBarFocusOut, true)
    cleanups.push(() => statusBarEl.removeEventListener('focusout', onStatusBarFocusOut, true))

    const domNode = editor.getDomNode()
    if (domNode) {
        const onFocus = async (): Promise<void> => {
            if (Date.now() - lastStatusBarBlurTime < 100) {
                return
            }
            try {
                const text = await navigator.clipboard.readText()
                regController.getRegister('+').setText(text)
            } catch {
                // clipboard permission denied or unavailable
            }
        }
        domNode.addEventListener('focus', onFocus, true)
        cleanups.push(() => domNode.removeEventListener('focus', onFocus, true))
    }

    return () => cleanups.forEach((fn) => fn())
}

export function setupVimMode(editor: monacoEditor.IStandaloneCodeEditor, statusBarEl: HTMLElement): VimModeHandle {
    const vimMode = initVimMode(editor, statusBarEl)
    const cmAdapter = vimMode as any

    const restoreAddOverlay = patchAddOverlay(cmAdapter)
    const restoreSetSec = patchSubstituteHighlight(cmAdapter, cmAdapter.statusBar)
    const cleanupClipboard = setupClipboardSync(editor, statusBarEl)

    return {
        vimMode,
        dispose: () => {
            cleanupClipboard()
            restoreSetSec()
            restoreAddOverlay()
            vimMode.dispose()
        },
    }
}
