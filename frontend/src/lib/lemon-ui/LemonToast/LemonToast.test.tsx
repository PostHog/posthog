import '@testing-library/jest-dom'

import { act, fireEvent, render } from '@testing-library/react'

import { GET_HELP_BUTTON, ToastContent, withClickableUrls } from './LemonToast'

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

    // Wiring guard for the error toast path: the message must go through the trusted-only
    // renderDetailWithLinks (URL linked in place, prose untouched), not a linkify-everything helper.
    it('links a PostHog URL in place without changing the message text', () => {
        const { container } = render(
            <>{withClickableUrls('Visit https://posthog.com/docs to fix this, then retry.')}</>
        )

        const link = container.querySelector('a')!
        expect(link).toHaveAttribute('href', 'https://posthog.com/docs')
        expect(container).toHaveTextContent('Visit https://posthog.com/docs to fix this, then retry.')
    })

    it('leaves a URL outside posthog.com as plain text', () => {
        const { container } = render(<>{withClickableUrls('More info: https://example.com/details')}</>)

        expect(container.querySelector('a')).toBeNull()
        expect(container).toHaveTextContent('More info: https://example.com/details')
    })

    it('returns a message without URLs unchanged', () => {
        expect(withClickableUrls('Load experiment failed')).toBe('Load experiment failed')
    })
})
