import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

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
    describe('slash command autocomplete', () => {
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
    })

    describe('send keyboard shortcut', () => {
        let maxLogicInstance: ReturnType<typeof maxLogic.build>
        let threadLogicInstance: ReturnType<typeof maxThreadLogic.build>

        beforeEach(() => {
            useMocks(maxMocks)
            initKeaTests()

            const maxGlobalLogicInstance = maxGlobalLogic()
            maxGlobalLogicInstance.mount()
            jest.spyOn(maxGlobalLogicInstance.selectors, 'dataProcessingAccepted').mockReturnValue(true)
        })

        afterEach(() => {
            cleanup()
            threadLogicInstance?.unmount()
            maxLogicInstance?.cache.eventSourceController?.abort()
            maxLogicInstance?.unmount()
            jest.restoreAllMocks()
        })

        // Renders the composer with the given send-key preference and a "hello world" draft,
        // then returns the textarea so the test only has to fire the key combo it cares about.
        const renderWithMode = (sendOnCmdEnter: boolean): HTMLTextAreaElement => {
            userLogic.mount()
            jest.spyOn(userLogic.selectors, 'user').mockReturnValue({
                ai_chat_send_on_cmd_enter: sendOnCmdEnter,
            } as unknown as UserType)

            maxLogicInstance = maxLogic({ panelId: 'test' })
            maxLogicInstance.mount()

            const threadProps = { panelId: 'test', conversationId: maxLogicInstance.values.frontendConversationId }
            threadLogicInstance = maxThreadLogic(threadProps)
            threadLogicInstance.mount()
            // Make the submission guard deterministic so the test isolates the keyboard handling.
            jest.spyOn(threadLogicInstance.selectors, 'submissionDisabledReason').mockReturnValue(undefined)
            jest.spyOn(threadLogicInstance.selectors, 'threadLoading').mockReturnValue(false)
            jest.spyOn(threadLogicInstance.actions, 'askMax').mockImplementation((() => undefined) as any)

            render(
                <Provider>
                    <BindLogic logic={maxLogic} props={{ panelId: 'test' }}>
                        <BindLogic logic={maxThreadLogic} props={threadProps}>
                            <QuestionInput />
                        </BindLogic>
                    </BindLogic>
                </Provider>
            )

            const input = screen.getByRole('textbox') as HTMLTextAreaElement
            fireEvent.change(input, { target: { value: 'hello world' } })
            return input
        }

        it.each([
            { name: 'default mode: Enter', sendOnCmdEnter: false, keyOpts: {} },
            { name: 'default mode: Cmd+Enter', sendOnCmdEnter: false, keyOpts: { metaKey: true } },
            { name: 'cmd-enter mode: Cmd+Enter', sendOnCmdEnter: true, keyOpts: { metaKey: true } },
            { name: 'cmd-enter mode: Ctrl+Enter', sendOnCmdEnter: true, keyOpts: { ctrlKey: true } },
        ])('sends the message ($name)', ({ sendOnCmdEnter, keyOpts }) => {
            const input = renderWithMode(sendOnCmdEnter)
            fireEvent.keyDown(input, { key: 'Enter', ...keyOpts })
            expect(threadLogicInstance.actions.askMax).toHaveBeenCalledWith('hello world')
        })

        it.each([
            { name: 'cmd-enter mode: plain Enter inserts a new line', sendOnCmdEnter: true, keyOpts: {} },
            // Default mode would normally send on plain Enter; the isComposing guard must suppress it
            // so CJK composition-commit Enter never sends the half-typed message.
            {
                name: 'default mode: Enter during IME composition',
                sendOnCmdEnter: false,
                keyOpts: { isComposing: true },
            },
            {
                name: 'default mode: Shift+Enter inserts a new line',
                sendOnCmdEnter: false,
                keyOpts: { shiftKey: true },
            },
            {
                name: 'cmd-enter mode: Shift+Enter inserts a new line',
                sendOnCmdEnter: true,
                keyOpts: { shiftKey: true },
            },
        ])('does not send the message ($name)', ({ sendOnCmdEnter, keyOpts }) => {
            const input = renderWithMode(sendOnCmdEnter)
            fireEvent.keyDown(input, { key: 'Enter', ...keyOpts })
            expect(threadLogicInstance.actions.askMax).not.toHaveBeenCalled()
        })
    })
})
