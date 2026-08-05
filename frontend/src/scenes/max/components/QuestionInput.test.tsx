import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

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
        const input = screen.getByRole('textbox') as HTMLTextAreaElement

        fireEvent.change(input, { target: { value: '/' } })
        await waitFor(() => expect(slashCommandItem()).toBeInTheDocument())

        fireEvent.keyDown(document, { key: 'Escape' })
        await waitFor(() => expect(slashCommandItem()).not.toBeInTheDocument())

        fireEvent.change(input, { target: { value: '' } })
        await waitFor(() => expect(input.value).toBe(''))

        fireEvent.change(input, { target: { value: '/' } })
        await waitFor(() => expect(slashCommandItem()).toBeInTheDocument())
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
