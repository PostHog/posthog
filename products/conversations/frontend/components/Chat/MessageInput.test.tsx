import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
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
        SupportEditor: ({ onCreate }: { onCreate: (editor: unknown) => void }) => {
            React.useEffect(() => {
                onCreate({ getJSON: () => ({ type: 'doc' }), clear: () => {} })
                // eslint-disable-next-line react-hooks/exhaustive-deps
            }, [])
            return React.createElement('div')
        },
        serializeToMarkdown: (): string => 'hello',
    }
})

const SEND_AND_SET_STATUS_OPTIONS: { value: TicketStatus; statusLabel: string }[] = [
    { value: 'pending', statusLabel: 'pending' },
    { value: 'on_hold', statusLabel: 'on hold' },
    { value: 'resolved', statusLabel: 'resolved' },
]

describe('MessageInput send-and-set-status dropdown', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
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
        // showCcBcc defaults off here, so no extra recipients ride along.
        expect(onSendMessage).toHaveBeenCalledWith(
            'hello',
            { type: 'doc' },
            isPrivate,
            expect.any(Function),
            'pending',
            undefined
        )
    })

    // Guards the Cc/Bcc wiring: when showCcBcc is on and the agent adds recipients, they must reach
    // onSendMessage — regressing this silently drops the extra recipients from the outbound email.
    test('passes Cc/Bcc recipients through to onSendMessage when showCcBcc is enabled', async () => {
        const onSendMessage = jest.fn()

        render(
            <Provider>
                <MessageInput
                    onSendMessage={onSendMessage}
                    messageSending={false}
                    showCcBcc
                    draftContent={{ type: 'doc', content: [] }}
                />
            </Provider>
        )

        await userEvent.click(screen.getByText('Add Cc/Bcc'))
        await userEvent.type(screen.getByPlaceholderText('Add Cc recipients...'), 'colleague@example.com{enter}')
        await userEvent.type(screen.getByPlaceholderText('Add Bcc recipients...'), 'finance@example.com{enter}')

        await userEvent.click(screen.getByText('Send'))
        expect(onSendMessage).toHaveBeenCalledWith(
            'hello',
            { type: 'doc' },
            false,
            expect.any(Function),
            undefined,
            { cc: ['colleague@example.com'], bcc: ['finance@example.com'] }
        )
    })
})
