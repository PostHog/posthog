import { editor as monacoEditor } from 'monaco-editor'
import { VimMode, initVimMode } from 'monaco-vim'

import { VimrcError, parseVimrc } from './vimrc'
import { VimMappingContext, VimrcMappingSession, createNonrecursiveVimMapping } from './vimrcMappings'

export interface VimModeHandle {
    vimMode: VimMode
    dispose: () => void
}

export interface VimModeProps {
    initialHistory?: string[]
    onCommandExecuted?: (command: string) => void
    vimrc?: string
}

interface VimrcEditorState {
    cursorBlink: boolean
    defaultLineNumbers: monacoEditor.LineNumbersType
}

const vimrcEditorStates = new WeakMap<object, VimrcEditorState>()
const vimrcMappingSession = new VimrcMappingSession()
let vimrcSupportRegistered = false

// Options and ex commands live on monaco-vim's global Vim object, which all editors share, so register them once.
function registerVimrcSupport(): void {
    if (vimrcSupportRegistered) {
        return
    }
    const Vim = (VimMode as any).Vim

    const noremapContexts: [string, VimMappingContext | undefined][] = [
        ['noremap', undefined],
        ['nnoremap', 'normal'],
        ['inoremap', 'insert'],
        ['vnoremap', 'visual'],
    ]
    for (const [name, context] of noremapContexts) {
        Vim.defineEx(name, name, (_cm: any, params: { args?: string[]; input: string }): void => {
            if (!params.args || params.args.length < 2) {
                throw new Error(`Invalid mapping: ${params.input}`)
            }
            createNonrecursiveVimMapping(params.args[0], params.args[1], context)
        })
    }

    // monaco-vim forces a solid cursor each time the editor enters normal mode. patchCursorBlink re-applies this option after that.
    Vim.defineOption('cursorblink', false, 'boolean', [], (value: boolean | undefined, cm?: any): boolean | void => {
        const state = cm && vimrcEditorStates.get(cm)
        if (!state) {
            return
        }
        if (value === undefined) {
            return state.cursorBlink
        }
        state.cursorBlink = value
        if (!cm.state.vim?.insertMode) {
            cm.editor.updateOptions({ cursorBlinking: value ? 'blink' : 'solid' })
        }
    })

    Vim.defineOption(
        'relativenumber',
        false,
        'boolean',
        ['rnu'],
        (value: boolean | undefined, cm?: any): boolean | void => {
            const state = cm && vimrcEditorStates.get(cm)
            if (!state) {
                return
            }
            if (value === undefined) {
                return cm.editor.getRawOptions().lineNumbers === 'relative'
            }
            cm.editor.updateOptions({ lineNumbers: value ? 'relative' : state.defaultLineNumbers })
        }
    )

    vimrcSupportRegistered = true
}

function patchCursorBlink(cmAdapter: any): () => void {
    const originalEnterVimMode = cmAdapter.enterVimMode

    cmAdapter.enterVimMode = function (...args: unknown[]): void {
        originalEnterVimMode.apply(this, args)
        if (vimrcEditorStates.get(cmAdapter)?.cursorBlink) {
            this.editor.updateOptions({ cursorBlinking: 'blink' })
        }
    }

    return () => {
        cmAdapter.enterVimMode = originalEnterVimMode
    }
}

// Runs each vimrc line as an ex command and returns an error for each line that failed. monaco-vim reports
// most failures through openNotification instead of throwing, so the notifications are captured while the lines run.
function applyVimrc(cmAdapter: any, vimrc: string): VimrcError[] {
    const Vim = (VimMode as any).Vim

    Vim.setOption('cursorblink', false, cmAdapter)
    Vim.setOption('relativenumber', false, cmAdapter)

    const { commands, errors } = parseVimrc(vimrc)
    const failures = [...errors]

    // Running a command overwrites the ":" register, which holds the last command the user typed.
    const lastCommandRegister = Vim.getRegisterController().getRegister(':')
    const lastCommand = lastCommandRegister.toString()
    const originalOpenNotification = cmAdapter.openNotification
    const captured: { notification: string | null } = { notification: null }
    cmAdapter.openNotification = (html: string | Node): void => {
        captured.notification = typeof html === 'string' ? html : html.textContent
    }

    try {
        for (const { lineNumber, command } of vimrcMappingSession.getCommandsToApply(commands)) {
            captured.notification = null
            try {
                Vim.handleEx(cmAdapter, command)
            } catch {
                // monaco-vim sends the error to openNotification before it rethrows, so the failure is already recorded.
            }
            if (captured.notification) {
                failures.push({ lineNumber, message: captured.notification })
            }
        }
    } finally {
        cmAdapter.openNotification = originalOpenNotification
        lastCommandRegister.setText(lastCommand)
    }

    return failures
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

// monaco-vim's statusbar passes `closeInput` as the `close` callback to
// onKeyDown/onKeyUp. But keymap_vim.ts calls `close(value)` with a string
// to mean "update the input" (the CodeMirror dialog convention), while
// closeInput() ignores arguments and always destroys the input. This breaks
// command/search history navigation with Up/Down arrows.
function patchCloseInput(statusBar: any): () => void {
    const originalCloseInput = statusBar.closeInput

    statusBar.closeInput = (newVal?: string): void => {
        if (typeof newVal === 'string') {
            if (statusBar.input?.node) {
                statusBar.input.node.value = newVal
            }
            return
        }
        originalCloseInput()
    }

    return () => {
        statusBar.closeInput = originalCloseInput
    }
}

// monaco-vim's monacoToCmKey expects Monaco-style key names ("UpArrow",
// "DownArrow") but the statusbar's input element fires native browser
// KeyboardEvents with e.key = "ArrowUp", "ArrowDown", etc. The
// endsWith("Arrow") check in monacoToCmKey fails for "ArrowUp", so
// onPromptKeyDown never sees "Up"/"Down" and history navigation breaks.
// Normalizing e.key on the status bar element in capture phase fixes this
// before the statusbar's inputKeyDown/inputKeyUp handlers read it.
const BROWSER_TO_MONACO_KEYS: Record<string, string> = {
    ArrowUp: 'UpArrow',
    ArrowDown: 'DownArrow',
    ArrowLeft: 'LeftArrow',
    ArrowRight: 'RightArrow',
}

function patchStatusBarArrowKeys(statusBarEl: HTMLElement): () => void {
    const normalizeKey = (e: KeyboardEvent): void => {
        const mapped = BROWSER_TO_MONACO_KEYS[e.key]
        if (mapped) {
            Object.defineProperty(e, 'key', { value: mapped, configurable: true })
        }
    }

    statusBarEl.addEventListener('keydown', normalizeKey, true)
    statusBarEl.addEventListener('keyup', normalizeKey, true)

    return () => {
        statusBarEl.removeEventListener('keydown', normalizeKey, true)
        statusBarEl.removeEventListener('keyup', normalizeKey, true)
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

// The pushInput patch is applied once globally since exCommandHistoryController
// lives on vimGlobalState (shared across all vim instances). Multiple editors
// can be mounted concurrently (e.g. SQL editor tabs), so we fan out to all
// registered callbacks.
const commandHistoryCallbacks = new Set<(command: string) => void>()
let pushInputPatched = false

function setupCommandHistoryPersistence(
    initialHistory: string[],
    onCommandExecuted: (command: string) => void
): () => void {
    const globalState = (VimMode as any).Vim.getVimGlobalState_()
    const controller = globalState.exCommandHistoryController

    if (!controller.historyBuffer.length && initialHistory.length) {
        controller.historyBuffer = [...initialHistory]
        controller.iterator = controller.historyBuffer.length
    }

    commandHistoryCallbacks.add(onCommandExecuted)

    if (!pushInputPatched) {
        const origPushInput = controller.pushInput.bind(controller)
        controller.pushInput = function (input: string): void {
            origPushInput(input)
            if (input) {
                commandHistoryCallbacks.forEach((cb) => cb(input))
            }
        }
        pushInputPatched = true
    }

    return () => {
        commandHistoryCallbacks.delete(onCommandExecuted)
    }
}

export function setupVimMode(
    editor: monacoEditor.IStandaloneCodeEditor,
    statusBarEl: HTMLElement,
    options?: VimModeProps
): VimModeHandle {
    registerVimrcSupport()
    const defaultLineNumbers = editor.getRawOptions().lineNumbers ?? 'on'
    const vimMode = initVimMode(editor, statusBarEl)
    const cmAdapter = vimMode as any
    vimrcEditorStates.set(cmAdapter, { cursorBlink: false, defaultLineNumbers })

    const restoreAddOverlay = patchAddOverlay(cmAdapter)
    const restoreCloseInput = patchCloseInput(cmAdapter.statusBar)
    const restoreArrowKeys = patchStatusBarArrowKeys(statusBarEl)
    const restoreSetSec = patchSubstituteHighlight(cmAdapter, cmAdapter.statusBar)
    const restoreCursorBlink = patchCursorBlink(cmAdapter)
    const cleanupClipboard = setupClipboardSync(editor, statusBarEl)

    const releaseVimrcMappings = vimrcMappingSession.retainEditor()
    const vimrcFailures = applyVimrc(cmAdapter, options?.vimrc ?? '')
    if (vimrcFailures.length) {
        const [{ lineNumber, message }] = vimrcFailures
        const more = vimrcFailures.length > 1 ? ` (and ${vimrcFailures.length - 1} more)` : ''
        cmAdapter.openNotification(`Couldn't apply vimrc line ${lineNumber}: ${message}${more}`)
    }

    let cleanupHistoryPersistence: (() => void) | undefined
    if (options?.onCommandExecuted) {
        cleanupHistoryPersistence = setupCommandHistoryPersistence(
            options.initialHistory ?? [],
            options.onCommandExecuted
        )
    }

    return {
        vimMode,
        dispose: () => {
            cleanupHistoryPersistence?.()
            releaseVimrcMappings()
            cleanupClipboard()
            restoreCursorBlink()
            restoreSetSec()
            restoreArrowKeys()
            restoreCloseInput()
            restoreAddOverlay()
            vimMode.dispose()
            editor.updateOptions({ lineNumbers: defaultLineNumbers })
        },
    }
}
