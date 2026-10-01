import { waitFor } from '@testing-library/react'

import { TerminalSession } from './TerminalSession'

describe('TerminalSession', () => {
    it('renders without WebGL and keeps the terminal surface out of session replay', async () => {
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
            await new Promise<void>((resolve) => session.view.write('Terminal ready', resolve))
            await waitFor(() => expect(container.querySelector('.xterm-rows')?.textContent).toContain('Terminal ready'))
        } finally {
            session.dispose()
            container.remove()
        }
    })
})
