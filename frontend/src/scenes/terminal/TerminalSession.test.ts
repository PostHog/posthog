import { TerminalSession, guardSelectionListeners } from './TerminalSession'

describe('TerminalSession', () => {
    it('keeps the terminal surface out of session replay before any output renders', () => {
        const session = new TerminalSession(
            () => {},
            () => {},
            () => {},
            () => {}
        )
        const container = document.createElement('div')
        document.body.append(container)
        try {
            session.attach(container)
            expect(container.firstElementChild?.classList.contains('ph-no-capture')).toBe(true)
            expect(container.firstElementChild?.classList.contains('ph-replay-block')).toBe(true)
        } finally {
            session.dispose()
            container.remove()
        }
    })

    it('keeps xterm from reporting a selection it cannot map as an unhandled error', () => {
        const listeners = guardSelectionListeners(() => {
            document.addEventListener('selectionchange', () => {
                throw new Error('invalid range')
            })
        })
        try {
            expect(() => document.dispatchEvent(new Event('selectionchange'))).not.toThrow()
        } finally {
            listeners.forEach((listener) => document.removeEventListener('selectionchange', listener))
        }
    })

    it('still reports every other selection failure', () => {
        const listeners = guardSelectionListeners(() => {
            document.addEventListener('selectionchange', () => {
                throw new Error('something else')
            })
        })
        const reported: string[] = []
        const onError = (event: ErrorEvent): void => {
            event.preventDefault()
            reported.push(event.error.message)
        }
        window.addEventListener('error', onError)
        try {
            document.dispatchEvent(new Event('selectionchange'))
            expect(reported).toEqual(['something else'])
        } finally {
            window.removeEventListener('error', onError)
            listeners.forEach((listener) => document.removeEventListener('selectionchange', listener))
        }
    })

    it('removes its document selection listener when the session is disposed', () => {
        const registered: EventListener[] = []
        const removed: EventListener[] = []
        const addEventListener = document.addEventListener.bind(document)
        const removeEventListener = document.removeEventListener.bind(document)
        document.addEventListener = (type: string, listener: EventListener, options?: unknown): void => {
            if (type === 'selectionchange') {
                registered.push(listener)
            }
            addEventListener(type, listener, options as AddEventListenerOptions)
        }
        let session: TerminalSession
        try {
            session = new TerminalSession(
                () => {},
                () => {},
                () => {},
                () => {}
            )
        } finally {
            Reflect.deleteProperty(document, 'addEventListener')
        }
        document.removeEventListener = (type: string, listener: EventListener, options?: unknown): void => {
            if (type === 'selectionchange') {
                removed.push(listener)
            }
            removeEventListener(type, listener, options as AddEventListenerOptions)
        }
        try {
            session.dispose()
        } finally {
            Reflect.deleteProperty(document, 'removeEventListener')
        }
        expect(registered).not.toHaveLength(0)
        expect(registered.filter((listener) => !removed.includes(listener))).toEqual([])
    })
})
