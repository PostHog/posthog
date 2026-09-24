import { act, fireEvent, render } from '@testing-library/react'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { CodeSnippet, Language } from './CodeSnippet'

jest.mock('lib/utils/copyToClipboard', () => ({
    copyToClipboard: jest.fn(),
}))

// Every case here renders with the highlighter chunk unavailable, as after a deploy removes it.
jest.mock('./HighlightedCodeLine', () => {
    throw new Error('highlighter chunk unavailable')
})

describe('CodeSnippet', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    // Callers hang telemetry off onCopy (capture events, product intents that mark adoption), so
    // firing it when copyToClipboard reported failure records a copy the user never got. That
    // happens for real: without navigator.clipboard (plain HTTP) or with the write denied,
    // copyToClipboard toasts the error and resolves false.
    it.each([
        ['reaches the clipboard', true, 1],
        ['fails to reach the clipboard', false, 0],
    ])('calls onCopy only when the snippet %s', async (_description, copied, expectedCalls) => {
        jest.mocked(copyToClipboard).mockResolvedValue(copied)
        const onCopy = jest.fn()
        const { container } = render(<CodeSnippet onCopy={onCopy}>echo hello</CodeSnippet>)

        fireEvent.click(container.querySelector('[data-attr="copy-code-button"]')!)
        await act(async () => {})

        expect(copyToClipboard).toHaveBeenCalledWith('echo hello', 'snippet')
        expect(onCopy).toHaveBeenCalledTimes(expectedCalls)
    })

    it('keeps the plain code when the highlighter fails to load', async () => {
        const { container } = render(<CodeSnippet language={Language.JavaScript}>const a = 1</CodeSnippet>)

        // The failed import settles over several microtasks, so let one macrotask pass.
        await act(async () => {
            await new Promise((resolve) => setTimeout(resolve, 0))
        })

        expect(container.querySelector('.CodeSnippet code')?.textContent).toBe('const a = 1')
    })
})
