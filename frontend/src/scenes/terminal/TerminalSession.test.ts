import { TerminalSession } from './TerminalSession'

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
})
