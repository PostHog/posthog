import { act, fireEvent, render } from '@testing-library/react'

import { GET_HELP_BUTTON, ToastContent } from './LemonToast'

describe('LemonToast', () => {
    const writeText = jest.fn((_text: string) => Promise.resolve())

    beforeEach(() => {
        jest.clearAllMocks()
        Object.assign(navigator, { clipboard: { writeText } })
    })

    // The copy button reads the rendered message out of the DOM, so it copies whatever sits inside the
    // message element. Widening that element to cover the action button would silently append "Get help"
    // to every error someone pastes elsewhere.
    it('copies the message without the action button label', async () => {
        const { container } = render(
            <ToastContent type="error" message="Load experiment failed" button={GET_HELP_BUTTON} />
        )

        fireEvent.click(container.querySelector('[data-attr="toast-copy-button"]')!)
        await act(async () => {})

        expect(writeText).toHaveBeenCalledWith('Load experiment failed')
    })

    it.each([
        ['error', true],
        ['warning', true],
        ['info', false],
        ['success', false],
    ] as const)('renders the copy button on a %s toast: %s', (type, expected) => {
        const { container } = render(<ToastContent type={type} message="A message" />)

        expect(!!container.querySelector('[data-attr="toast-copy-button"]')).toBe(expected)
    })
})
