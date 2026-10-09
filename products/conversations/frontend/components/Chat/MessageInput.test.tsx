import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import type { TicketStatus } from '../../types'
import { MessageInput } from './MessageInput'

// The real SupportEditor pulls in tiptap, mentions, and uploads; the behavior under test is
// MessageInput's own wiring, which only needs an editor exposing getJSON().
jest.mock('../Editor', () => {
    const React = jest.requireActual<typeof import('react')>('react')
    return {
        SupportEditor: ({
            onCreate,
            onPressCmdEnter,
            disabled,
            autoFocus,
            header,
        }: {
            onCreate: (editor: unknown) => void
            onPressCmdEnter: () => void
            disabled?: boolean
            autoFocus?: boolean
            header?: React.ReactNode
        }) => {
            React.useEffect(() => {
                const el = document.querySelector('[data-attr="support-editor"]') as HTMLElement | null
                const editor = {
                    getJSON: () => ({ type: 'doc' }),
                    clear: () => {},
                    setContent: () => {},
                    isEmpty: () => false,
                    focus: () => el?.focus(),
                }
                onCreate(editor)
                if (autoFocus) {
                    editor.focus()
                }
                // eslint-disable-next-line react-hooks/exhaustive-deps
            }, [])
            return React.createElement(
                React.Fragment,
                null,
                header,
                React.createElement(
                    'button',
                    { 'data-attr': 'support-editor', 'data-disabled': disabled, onClick: onPressCmdEnter },
                    'Editor shortcut'
                )
            )
        },
        serializeToMarkdown: (): string => 'hello',
    }
})

const SEND_AND_SET_STATUS_OPTIONS: { value: TicketStatus; statusLabel: string }[] = [
    { value: 'pending', statusLabel: 'pending' },
    { value: 'on_hold', statusLabel: 'on hold' },
    { value: 'resolved', statusLabel: 'resolved' },
]

describe('MessageInput', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('disables the editor and blocks its keyboard submit shortcut without edit access', async () => {
        const onSendMessage = jest.fn()

        render(
            <Provider>
                <MessageInput
                    onSendMessage={onSendMessage}
                    messageSending={false}
                    draftContent={{ type: 'doc', content: [] }}
                    sendDisabledReason="Requires edit access"
                />
            </Provider>
        )

        const editor = screen.getByTestId('support-editor')
        expect(editor).toHaveAttribute('data-disabled', 'true')
        await userEvent.click(editor)
        expect(onSendMessage).not.toHaveBeenCalled()
    })

    // Guards the private-note flag through the dropdown path: dropping it would deliver an
    // internal note to the customer as a real reply.
    test.each<[string, boolean, string]>([
        ['regular mode', false, 'Send'],
        ['private note mode', true, 'Attach'],
    ])('in %s the dropdown labels use the mode verb and preserve the private flag', async (_name, isPrivate, verb) => {
        const onSendMessage = jest.fn()

        render(
            <Provider>
                <MessageInput
                    onSendMessage={onSendMessage}
                    messageSending={false}
                    showPrivateOption
                    isPrivate={isPrivate}
                    onPrivateChange={jest.fn()}
                    draftMode={false}
                    onDraftModeChange={jest.fn()}
                    draftContent={{ type: 'doc', content: [] }}
                    sendAndSetStatusOptions={SEND_AND_SET_STATUS_OPTIONS}
                />
            </Provider>
        )

        // Draft mode has no effect on private notes, so its switch is disabled in private note mode
        expect(screen.getByRole('switch')).toHaveProperty('disabled', isPrivate)

        await userEvent.click(screen.getByLabelText(`${verb} and set ticket status`))
        expect(await screen.findByText(`${verb} and set pending`)).toBeInTheDocument()
        expect(screen.getByText(`${verb} and set on hold`)).toBeInTheDocument()
        expect(screen.getByText(`${verb} and set resolved`)).toBeInTheDocument()

        await userEvent.click(screen.getByText(`${verb} and set pending`))
        expect(onSendMessage).toHaveBeenCalledTimes(1)
        expect(onSendMessage).toHaveBeenCalledWith('hello', { type: 'doc' }, isPrivate, expect.any(Function), 'pending')
    })

    describe('simplified replies', () => {
        function renderSimplified(onSendMessage = jest.fn()): jest.Mock {
            render(
                <Provider>
                    <MessageInput
                        onSendMessage={onSendMessage}
                        messageSending={false}
                        channel="slack"
                        showPrivateOption
                        draftMode
                        onDraftModeChange={jest.fn()}
                        draftContent={{ type: 'doc', content: [] }}
                        sendConfirmationMessage="This will send to the linked Slack thread"
                        sendAndSetStatusOptions={SEND_AND_SET_STATUS_OPTIONS}
                        simplifiedReplies={{ recipient: 'Ada Example', statusLabel: 'Open' }}
                    />
                </Provider>
            )
            return onSendMessage
        }

        it('names the destination, recipient and status above the editor, and drops draft mode', () => {
            renderSimplified()

            const header = screen.getByTestId('composer-header')
            expect(header).toHaveTextContent('Reply in Slack')
            expect(header).toHaveTextContent('Ada Example')
            expect(header).toHaveTextContent('Ticket status: Open')
            expect(screen.queryByRole('switch')).not.toBeInTheDocument()
        })

        // Send only opens the menu: sending straight from the button would skip the confirm step this replaces.
        it('sends nothing until a row is picked, then sends with that status', async () => {
            const onSendMessage = renderSimplified()

            await userEvent.click(screen.getByRole('button', { name: /^Send/ }))
            expect(onSendMessage).not.toHaveBeenCalled()
            expect(await screen.findByText('This will send to the linked Slack thread')).toBeInTheDocument()

            await userEvent.click(screen.getByText('Send and set resolved'))
            expect(onSendMessage).toHaveBeenCalledWith(
                'hello',
                { type: 'doc' },
                false,
                expect.any(Function),
                'resolved'
            )
        })

        test.each<[string, string, TicketStatus | undefined]>([
            ['Enter keeps the status', '{Enter}', undefined],
            ['a digit sets the numbered status', '2', 'on_hold'],
        ])('%s', async (_name, keys, status) => {
            const onSendMessage = renderSimplified()

            // The editor's Cmd+Enter shortcut opens the menu instead of sending.
            await userEvent.click(screen.getByTestId('support-editor'))
            expect(onSendMessage).not.toHaveBeenCalled()
            expect(await screen.findByTestId('send-menu')).toBeInTheDocument()

            await userEvent.keyboard(keys)
            expect(onSendMessage).toHaveBeenCalledTimes(1)
            expect(onSendMessage).toHaveBeenCalledWith('hello', { type: 'doc' }, false, expect.any(Function), status)
        })

        it('Enter on a focused menu row sends with that row, not the default', async () => {
            const onSendMessage = renderSimplified()

            await userEvent.click(screen.getByTestId('support-editor'))
            expect(await screen.findByTestId('send-menu')).toBeInTheDocument()

            screen.getByRole('menuitem', { name: /Send and set resolved/ }).focus()
            await userEvent.keyboard('{Enter}')
            expect(onSendMessage).toHaveBeenCalledTimes(1)
            expect(onSendMessage).toHaveBeenCalledWith(
                'hello',
                { type: 'doc' },
                false,
                expect.any(Function),
                'resolved'
            )
        })

        test.each<[string, string]>([
            ['Enter', '{Enter}'],
            ['a digit', '2'],
        ])('%s in a field outside the composer does not send', async (_name, keys) => {
            const onSendMessage = renderSimplified()
            render(<input aria-label="Sidebar field" />)

            await userEvent.click(screen.getByTestId('support-editor'))
            expect(await screen.findByTestId('send-menu')).toBeInTheDocument()

            screen.getByLabelText('Sidebar field').focus()
            await userEvent.keyboard(keys)
            expect(onSendMessage).not.toHaveBeenCalled()
        })

        test.each<[string, string]>([
            ['an Enter that confirms', 'Enter'],
            ['a digit that picks a candidate in', '2'],
        ])('%s an IME composition does not send', async (_name, key) => {
            const onSendMessage = renderSimplified()

            await userEvent.click(screen.getByTestId('support-editor'))
            expect(await screen.findByTestId('send-menu')).toBeInTheDocument()

            fireEvent.keyDown(screen.getByTestId('support-editor'), { key, isComposing: true, keyCode: 229 })
            expect(onSendMessage).not.toHaveBeenCalled()
        })

        it('goes back to the draft on Escape', async () => {
            const onSendMessage = renderSimplified()

            await userEvent.click(screen.getByTestId('support-editor'))
            expect(await screen.findByTestId('send-menu')).toBeInTheDocument()

            await userEvent.keyboard('{Escape}')
            expect(onSendMessage).not.toHaveBeenCalled()
            await waitFor(() => expect(screen.queryByTestId('send-menu')).not.toBeInTheDocument())
        })
    })
})

describe('MessageInput collapsed composer', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('shows a one-line field until focused, then the full composer', async () => {
        render(
            <Provider>
                <MessageInput onSendMessage={jest.fn()} messageSending={false} collapseUntilActive />
            </Provider>
        )

        expect(screen.queryByTestId('support-editor')).not.toBeInTheDocument()
        await userEvent.click(screen.getByPlaceholderText('Type your message...'))
        expect(screen.getByTestId('support-editor')).toBeInTheDocument()
        expect(screen.getByTestId('support-editor')).toHaveFocus()
    })

    it('collapses again when the thread id changes', async () => {
        const { rerender } = render(
            <Provider>
                <MessageInput
                    onSendMessage={jest.fn()}
                    messageSending={false}
                    collapseUntilActive
                    threadId="ticket-a"
                />
            </Provider>
        )

        await userEvent.click(screen.getByPlaceholderText('Type your message...'))
        expect(screen.getByTestId('support-editor')).toBeInTheDocument()

        rerender(
            <Provider>
                <MessageInput
                    onSendMessage={jest.fn()}
                    messageSending={false}
                    collapseUntilActive
                    threadId="ticket-b"
                />
            </Provider>
        )

        expect(screen.queryByTestId('support-editor')).not.toBeInTheDocument()
        expect(screen.getByPlaceholderText('Type your message...')).toBeInTheDocument()
    })

    test.each([
        ['draft content', { draftContent: { type: 'doc', content: [] } }],
        ['editing a message', { editingMessageId: 'note-1' }],
    ])('starts expanded with %s', (_name, extraProps) => {
        render(
            <Provider>
                <MessageInput onSendMessage={jest.fn()} messageSending={false} collapseUntilActive {...extraProps} />
            </Provider>
        )

        expect(screen.getByTestId('support-editor')).toBeInTheDocument()
        expect(screen.queryByPlaceholderText('Type your message...')).not.toBeInTheDocument()
    })
})

describe('MessageInput editing mode', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    test('shows Save and Cancel, and locks the private checkbox', () => {
        const onCancelEdit = jest.fn()

        render(
            <Provider>
                <MessageInput
                    onSendMessage={jest.fn()}
                    messageSending={false}
                    showPrivateOption
                    isPrivate
                    onPrivateChange={jest.fn()}
                    draftContent={{ type: 'doc', content: [] }}
                    editingMessageId="note-1"
                    onCancelEdit={onCancelEdit}
                />
            </Provider>
        )

        expect(screen.getByText('Save')).toBeInTheDocument()
        expect(screen.getByText('Cancel')).toBeInTheDocument()
        expect(screen.queryByLabelText(/and set ticket status/)).not.toBeInTheDocument()

        const checkbox = screen.getByRole('checkbox')
        expect(checkbox).toBeDisabled()
    })
})
