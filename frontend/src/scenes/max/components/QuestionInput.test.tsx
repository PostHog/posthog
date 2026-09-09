import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { MAX_MESSAGE_LENGTH } from '../max-constants'
import { maxGlobalLogic } from '../maxGlobalLogic'
import { maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'
import { maxMocks } from '../testUtils'
import { QuestionInput } from './QuestionInput'

jest.mock(
    '@posthog/hogvm',
    () => ({
        exec: jest.fn(),
        execAsync: jest.fn(),
    }),
    { virtual: true }
)

describe('QuestionInput', () => {
    let maxLogicInstance: ReturnType<typeof maxLogic.build>
    let threadLogicInstance: ReturnType<typeof maxThreadLogic.build>

    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()

        const maxGlobalLogicInstance = maxGlobalLogic()
        maxGlobalLogicInstance.mount()
        jest.spyOn(maxGlobalLogicInstance.selectors, 'dataProcessingAccepted').mockReturnValue(true)

        maxLogicInstance = maxLogic({ panelId: 'test' })
        maxLogicInstance.mount()

        const threadProps = { panelId: 'test', conversationId: maxLogicInstance.values.frontendConversationId }
        threadLogicInstance = maxThreadLogic(threadProps)
        threadLogicInstance.mount()

        render(
            <Provider>
                <BindLogic logic={maxLogic} props={{ panelId: 'test' }}>
                    <BindLogic logic={maxThreadLogic} props={threadProps}>
                        <QuestionInput />
                    </BindLogic>
                </BindLogic>
            </Provider>
        )
    })

    afterEach(() => {
        cleanup()
        threadLogicInstance?.unmount()
        maxLogicInstance?.cache.eventSourceController?.abort()
        maxLogicInstance?.unmount()
        jest.restoreAllMocks()
    })

    const slashCommandItem = (): HTMLElement | null => screen.queryByText('/init')

    const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0))

    it('does not release a sandbox pre-warm when blur moves to the send button', async () => {
        // Simulate a completed warm; a release would clear the flag (and relay-cancel the warm Run).
        threadLogicInstance.cache.prewarmed = true
        threadLogicInstance.cache.prewarming = false

        const input = screen.getByRole('textbox') as HTMLTextAreaElement
        const sendButton = document.querySelector('[data-attr="max-send-message"]') as HTMLElement
        expect(sendButton).not.toBeNull()

        // Clicking send blurs the textarea before the click fires the send — the warm must survive.
        fireEvent.blur(input, { relatedTarget: sendButton })
        await flush()

        // Blur-to-send does not trigger releaseSandboxPrewarm, so the warm is untouched.
        expect(threadLogicInstance.cache.prewarmed).toBe(true)
    })

    it('releases a sandbox pre-warm when blur leaves the input for somewhere else', async () => {
        threadLogicInstance.cache.prewarmed = true
        threadLogicInstance.cache.prewarming = false

        const input = screen.getByRole('textbox') as HTMLTextAreaElement

        fireEvent.blur(input, { relatedTarget: null })
        await flush()

        // Blur-away triggers releaseSandboxPrewarm, which clears the flag (and relay-cancels any warm Run).
        expect(threadLogicInstance.cache.prewarmed).toBe(false)
    })

    it('reopens the popover after Escape dismisses it and a fresh slash is typed', async () => {
        const user = userEvent.setup()
        const input = screen.getByRole('textbox') as HTMLTextAreaElement

        await user.type(input, '/')
        await waitFor(() => expect(slashCommandItem()).toBeInTheDocument())

        await user.keyboard('{Escape}')
        await waitFor(() => expect(slashCommandItem()).not.toBeInTheDocument())

        await user.clear(input)
        await waitFor(() => expect(input.value).toBe(''))

        await user.type(input, '/')
        await waitFor(() => expect(slashCommandItem()).toBeInTheDocument())
    })

    describe('message length limit', () => {
        const sendButton = (): HTMLElement | null => document.querySelector('[data-attr="max-send-message"]')

        it('blocks a message the server would reject, and counts it in code points', async () => {
            const input = screen.getByRole('textbox') as HTMLTextAreaElement

            // Emoji are one code point each but two UTF-16 units, so a naive `String.length` check
            // would block this message even though the server accepts it.
            fireEvent.change(input, { target: { value: '😀'.repeat(MAX_MESSAGE_LENGTH) } })
            await waitFor(() => expect(sendButton()).not.toHaveAttribute('aria-disabled', 'true'))

            fireEvent.change(input, { target: { value: 'x'.repeat(MAX_MESSAGE_LENGTH + 1) } })
            await waitFor(() => expect(sendButton()).toHaveAttribute('aria-disabled', 'true'))
            expect(screen.getByText('40,001 / 40,000')).toBeInTheDocument()
        })

        it('leaves the counter out of the way until the message approaches the limit', async () => {
            const input = screen.getByRole('textbox') as HTMLTextAreaElement

            fireEvent.change(input, { target: { value: 'a short question' } })
            await waitFor(() => expect(input.value).toBe('a short question'))
            expect(screen.queryByText(/\/ 40,000$/)).not.toBeInTheDocument()
        })

        it('sends the whole suggestion when the send lands mid-animation', async () => {
            const askMaxSpy = jest.spyOn(threadLogicInstance.actions, 'askMax')
            const suggestion = 'What is the retention in the last two weeks?'

            maxLogicInstance.actions.runSuggestion({ content: suggestion })
            // The typewriter has only written the first character, so the composer shows a prefix.
            await waitFor(() => expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('W'))

            fireEvent.click(sendButton() as HTMLElement)

            expect(askMaxSpy).toHaveBeenCalledWith(suggestion)
        })
    })

    describe('stop button cancel state', () => {
        const sendButton = (): HTMLElement | null => document.querySelector('[data-attr="max-send-message"]')
        const stopButton = (): HTMLElement | null => document.querySelector('[data-attr="max-stop-generation"]')

        it('shows the stop affordance while streaming and not cancelling', async () => {
            threadLogicInstance.actions.reconnectToStream()
            await waitFor(() => expect(stopButton()).not.toBeNull())
            expect(sendButton()).toHaveAttribute('aria-disabled', 'true')
        })

        it('shows send (not stop) while cancelLoading is true', async () => {
            threadLogicInstance.actions.reconnectToStream()
            threadLogicInstance.actions.setCancelLoading(true)

            await waitFor(() => expect(sendButton()).not.toBeNull())
            expect(stopButton()).toBeNull()
            // The composer button reads "Cancelling…" via disabledReason, never "Let's bail".
            expect(screen.queryByText("Let's bail")).not.toBeInTheDocument()
        })

        it('returns to send (not stop) after cancel resolves and loading clears', async () => {
            threadLogicInstance.actions.reconnectToStream()
            threadLogicInstance.actions.setCancelLoading(true)
            await waitFor(() => expect(sendButton()).not.toBeNull())

            // Cancel resolves: streaming ends and cancelLoading clears -> threadLoading false.
            threadLogicInstance.actions.endStreaming()
            threadLogicInstance.actions.setCancelLoading(false)

            await waitFor(() => expect(sendButton()).not.toBeNull())
            expect(stopButton()).toBeNull()
            expect(screen.queryByText("Let's bail")).not.toBeInTheDocument()
        })
    })
})
