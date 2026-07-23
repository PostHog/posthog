import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import type { TicketStatus } from '../../types'
import { MessageInput } from './MessageInput'

// The real SupportEditor pulls in tiptap, mentions, and uploads; the behavior under test is
// MessageInput's own wiring, which only needs an editor exposing the buffer API. The mock is
// stateful so tab switches (setContent) and stash-on-switch (getJSON) can be asserted.
const mockEditorHolder: { current: any } = { current: null }
jest.mock('../Editor', () => {
    const React = jest.requireActual<typeof import('react')>('react')
    return {
        SupportEditor: ({ onCreate }: { onCreate: (editor: unknown) => void }) => {
            React.useEffect(() => {
                // getJSON is stable so callers can assert on it; emptiness is driven by
                // MessageInput's own state (seeded from the active draft prop), not the editor.
                mockEditorHolder.current = {
                    getJSON: () => ({ type: 'doc' }),
                    setContent: jest.fn(),
                    clear: jest.fn(),
                    isEmpty: () => false,
                    focus: jest.fn(),
                }
                onCreate(mockEditorHolder.current)
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

const NON_EMPTY_DOC = { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'x' }] }] }

describe('MessageInput send-and-set-status dropdown', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    // Guards the private-note flag through the dropdown path: dropping it would deliver a
    // private note to the customer as a real reply.
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
                    draftContent={NON_EMPTY_DOC}
                    privateDraftContent={NON_EMPTY_DOC}
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
})

describe('MessageInput reply/private-note tabs', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        mockEditorHolder.current = null
    })

    it('stashes the current tab body and switches active tab on tab change', async () => {
        const onDraftChange = jest.fn()
        const onPrivateDraftChange = jest.fn()
        const onPrivateChange = jest.fn()

        render(
            <Provider>
                <MessageInput
                    onSendMessage={jest.fn()}
                    messageSending={false}
                    showPrivateOption
                    isPrivate={false}
                    onPrivateChange={onPrivateChange}
                    draftContent={NON_EMPTY_DOC}
                    onDraftChange={onDraftChange}
                    privateDraftContent={null}
                    onPrivateDraftChange={onPrivateDraftChange}
                />
            </Provider>
        )

        await userEvent.click(screen.getByText('Private note'))

        // The reply body in the editor is stashed to the public buffer, and the active tab flips.
        expect(onDraftChange).toHaveBeenCalledWith(mockEditorHolder.current.getJSON())
        expect(onPrivateDraftChange).not.toHaveBeenCalled()
        expect(onPrivateChange).toHaveBeenCalledWith(true)
    })

    it('clears only the sent tab and preserves the other draft', async () => {
        const onSendMessage = jest.fn((_c, _r, _p, onSuccess: () => void) => onSuccess())
        const onDraftChange = jest.fn()
        const onPrivateDraftChange = jest.fn()

        render(
            <Provider>
                <MessageInput
                    onSendMessage={onSendMessage}
                    messageSending={false}
                    showPrivateOption
                    isPrivate={false}
                    onPrivateChange={jest.fn()}
                    draftContent={NON_EMPTY_DOC}
                    onDraftChange={onDraftChange}
                    privateDraftContent={NON_EMPTY_DOC}
                    onPrivateDraftChange={onPrivateDraftChange}
                />
            </Provider>
        )

        await userEvent.click(screen.getByRole('button', { name: 'Send' }))

        // The reply buffer is cleared; the private-note buffer is never touched.
        expect(onSendMessage).toHaveBeenCalledWith('hello', { type: 'doc' }, false, expect.any(Function), undefined)
        expect(onDraftChange).toHaveBeenLastCalledWith(null)
        expect(onPrivateDraftChange).not.toHaveBeenCalled()
    })
})
