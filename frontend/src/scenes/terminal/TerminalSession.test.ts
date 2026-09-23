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

    it.each([
        ['invalid range', []],
        ['something else', ['something else']],
    ])('the xterm selection listener throwing "%s"', (message, expected) => {
        const guard = new AbortController()
        guardSelectionListeners(() => {
            document.addEventListener('selectionchange', () => {
                throw new Error(message)
            })
        }, guard.signal)
        const reported: string[] = []
        const onError = (event: ErrorEvent): void => {
            event.preventDefault()
            reported.push(event.error.message)
        }
        window.addEventListener('error', onError)
        try {
            document.dispatchEvent(new Event('selectionchange'))
        } finally {
            window.removeEventListener('error', onError)
            guard.abort()
        }
        expect(reported).toEqual(expected)
    })

    it('detaches the guarded listener once the signal is aborted', () => {
        const guard = new AbortController()
        let calls = 0
        guardSelectionListeners(() => {
            document.addEventListener('selectionchange', () => {
                calls++
            })
        }, guard.signal)
        document.dispatchEvent(new Event('selectionchange'))
        guard.abort()
        document.dispatchEvent(new Event('selectionchange'))
        expect(calls).toBe(1)
    })

    it('wraps and detaches the listener xterm registers when the terminal opens', () => {
        const addEventListener = jest.spyOn(document, 'addEventListener')
        const removeEventListener = jest.spyOn(document, 'removeEventListener')
        try {
            const session = new TerminalSession(
                () => {},
                () => {},
                () => {},
                () => {}
            )
            const registered = addEventListener.mock.calls.filter(([type]) => type === 'selectionchange')
            expect(registered).not.toHaveLength(0)
            session.dispose()
            // xterm disposes by the unwrapped function, so what it removes must not be what was attached.
            const unwrapped = removeEventListener.mock.calls
                .filter(([type]) => type === 'selectionchange')
                .map(([, listener]) => listener)
            expect(unwrapped).not.toHaveLength(0)
            for (const [, listener, options] of registered) {
                expect(unwrapped).not.toContain(listener)
                expect((options as AddEventListenerOptions).signal?.aborted).toBe(true)
            }
        } finally {
            addEventListener.mockRestore()
            removeEventListener.mockRestore()
        }
    })
})
