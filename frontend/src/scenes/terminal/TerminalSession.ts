import '@xterm/xterm/css/xterm.css'

import { FitAddon } from '@xterm/addon-fit'
import { Terminal } from '@xterm/xterm'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

/**
 * xterm's accessibility manager listens for `selectionchange` on the whole document, and throws
 * "invalid range" when it maps a selection to an empty terminal range. Nothing catches a throw from
 * an event listener, so it reaches error tracking as an unhandled exception. Wrap every
 * `selectionchange` listener that `register` adds, and return the wrappers, because xterm keeps the
 * unwrapped function and cannot remove them itself.
 */
export function guardSelectionListeners(register: () => void): EventListener[] {
    const wrappers: EventListener[] = []
    const addEventListener = document.addEventListener.bind(document)
    document.addEventListener = (
        type: string,
        listener: EventListenerOrEventListenerObject,
        options?: boolean | AddEventListenerOptions
    ): void => {
        if (type !== 'selectionchange' || typeof listener !== 'function') {
            addEventListener(type, listener, options)
            return
        }
        const wrapper = (event: Event): void => {
            try {
                listener(event)
            } catch (error) {
                if (!(error instanceof Error) || error.message !== 'invalid range') {
                    throw error
                }
            }
        }
        wrappers.push(wrapper)
        addEventListener(type, wrapper, options)
    }
    try {
        register()
    } finally {
        Reflect.deleteProperty(document, 'addEventListener')
    }
    return wrappers
}

export class TerminalSession {
    private readonly colors = getComputedStyle(document.documentElement)
    readonly view = new Terminal({
        cursorBlink: true,
        scrollback: 10_000,
        fontSize: 13,
        fontFamily: 'monospace',
        screenReaderMode: true,
        rightClickSelectsWord: true,
        macOptionClickForcesSelection: true,
        theme: {
            background: '#000000',
            foreground: this.colors.getPropertyValue('--color-gray-200').trim(),
            cursor: this.colors.getPropertyValue('--color-gray-200').trim(),
            selectionBackground: this.colors.getPropertyValue('--color-gray-700').trim(),
            black: '#000000',
            red: this.colors.getPropertyValue('--color-red-400').trim(),
            green: this.colors.getPropertyValue('--color-green-400').trim(),
            yellow: this.colors.getPropertyValue('--color-yellow-400').trim(),
            blue: this.colors.getPropertyValue('--color-blue-400').trim(),
            magenta: this.colors.getPropertyValue('--color-purple-400').trim(),
            cyan: this.colors.getPropertyValue('--color-cyan-400').trim(),
            white: this.colors.getPropertyValue('--color-gray-200').trim(),
            brightBlack: this.colors.getPropertyValue('--color-gray-400').trim(),
            brightRed: this.colors.getPropertyValue('--color-red-300').trim(),
            brightGreen: this.colors.getPropertyValue('--color-green-300').trim(),
            brightYellow: this.colors.getPropertyValue('--color-yellow-300').trim(),
            brightBlue: this.colors.getPropertyValue('--color-blue-300').trim(),
            brightMagenta: this.colors.getPropertyValue('--color-purple-300').trim(),
            brightCyan: this.colors.getPropertyValue('--color-cyan-300').trim(),
            brightWhite: '#ffffff',
        },
    })
    private readonly element = document.createElement('div')
    private readonly fit = new FitAddon()
    private readonly observer = new ResizeObserver(() => this.resize())
    private readonly guardedSelectionListeners: EventListener[]

    constructor(
        write: (data: string) => void,
        resize: (columns: number, rows: number) => void,
        select: (selected: boolean) => void,
        paste: () => void
    ) {
        // Shell commands and project data must stay out of autocapture and session replay.
        this.element.className = 'h-full min-w-0 bg-black ph-no-capture ph-replay-block'
        this.element.dataset.shortcutsIgnore = 'ctrl'
        this.element.dataset.shortcutsAllowKeys = '` ~'
        this.view.loadAddon(this.fit)
        this.guardedSelectionListeners = guardSelectionListeners(() => this.view.open(this.element))
        this.view.onData(write)
        this.view.onResize(({ cols, rows }) => resize(cols, rows))
        this.view.onSelectionChange(() => {
            select(this.view.hasSelection())
            if (this.view.hasSelection()) {
                void copyToClipboard(this.view.getSelection(), 'terminal selection', { silent: true })
            }
        })
        this.view.attachCustomKeyEventHandler((event) => {
            if (event.ctrlKey && !event.metaKey) {
                event.stopPropagation()
            }
            const key = event.key.toLowerCase()
            if ((event.metaKey || (event.ctrlKey && event.shiftKey)) && (key === 'c' || key === 'v')) {
                event.stopPropagation()
                if (key === 'c' || !event.metaKey) {
                    event.preventDefault()
                    if (event.type === 'keydown') {
                        if (key === 'c' && this.view.hasSelection()) {
                            void copyToClipboard(this.view.getSelection(), 'terminal selection')
                        } else if (key === 'v') {
                            paste()
                        }
                    }
                }
                return false
            }
            return true
        })
        this.observer.observe(this.element)
    }

    attach(container: HTMLElement): void {
        container.appendChild(this.element)
        this.resize()
        this.view.focus()
    }

    detach(container: HTMLElement): void {
        if (this.element.parentElement === container) {
            this.element.remove()
        }
    }

    resize(): void {
        if (this.element.clientWidth && this.element.clientHeight) {
            this.fit.fit()
        }
    }

    dispose(): void {
        this.observer.disconnect()
        for (const listener of this.guardedSelectionListeners) {
            document.removeEventListener('selectionchange', listener)
        }
        this.view.dispose()
        this.element.remove()
    }
}
