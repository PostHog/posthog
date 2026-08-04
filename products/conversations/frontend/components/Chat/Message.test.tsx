import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import type { ChatMessage } from '../../types'
import { Message } from './Message'

// The real editor exports pull in tiptap, mentions, and uploads; the behavior under test is which
// affordances Message renders, which only needs an editor exposing getJSON().
jest.mock('../Editor', () => {
    const React = jest.requireActual<typeof import('react')>('react')
    return {
        // Stands in for the editor: `type` mutates the document the way a keystroke would, so the
        // form's changed/unchanged handling can be exercised without tiptap.
        SupportEditor: ({ onCreate, onUpdate }: { onCreate: (editor: unknown) => void; onUpdate: () => void }) => {
            const docRef = React.useRef<{ type: string; edited?: boolean }>({ type: 'doc' })
            React.useEffect(() => {
                onCreate({ getJSON: () => docRef.current, focus: () => {} })
                // eslint-disable-next-line react-hooks/exhaustive-deps
            }, [])
            return React.createElement(
                'button',
                {
                    'data-attr': 'simulate-typing',
                    onClick: () => {
                        docRef.current = { type: 'doc', edited: true }
                        onUpdate()
                    },
                },
                'type'
            )
        },
        serializeToMarkdown: (doc: { edited?: boolean }): string => (doc.edited ? 'edited markdown' : 'the note body'),
        messageBodyToRichContent: (content: string) => ({
            type: 'doc',
            content: [{ type: 'paragraph', content: [{ type: 'text', text: content }] }],
        }),
        SupportMarkdown: ({ children }: { children: string }) =>
            React.createElement('div', { 'data-attr': 'message-body' }, children),
        SupportRichContentPreview: () => React.createElement('div', { 'data-attr': 'message-body' }),
    }
})

function privateNote(overrides: Partial<ChatMessage> = {}): ChatMessage {
    return {
        id: 'note-1',
        content: 'the note body',
        authorType: 'human',
        authorName: 'Agent',
        createdAt: '2026-01-01T00:00:00Z',
        isPrivate: true,
        ...overrides,
    }
}

describe('Message', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    // The Edit button is the whole affordance: showing it on a note the reader can't edit sends them
    // into a 403, and hiding it on their own newest note removes the feature.
    test.each<[string, Partial<ChatMessage>, boolean, boolean]>([
        ['an editable private note', { isPrivate: true }, true, true],
        ['a private note that is not editable', { isPrivate: true }, false, false],
        ['a public reply', { isPrivate: false }, true, false],
    ])('%s renders the edit button: %s', async (_name, overrides, canEdit, expected) => {
        render(
            <Message message={privateNote(overrides)} isCustomer={false} canEdit={canEdit} onStartEdit={jest.fn()} />
        )

        expect(!!screen.queryByTestId('edit-private-note')).toBe(expected)
    })

    it('starts editing when the edit button is clicked', async () => {
        const onStartEdit = jest.fn()
        render(<Message message={privateNote()} isCustomer={false} canEdit onStartEdit={onStartEdit} />)

        await userEvent.click(screen.getByTestId('edit-private-note'))

        expect(onStartEdit).toHaveBeenCalledTimes(1)
    })

    it('blocks editing with a reason when the reader lacks ticket access', async () => {
        const onStartEdit = jest.fn()
        render(
            <Message
                message={privateNote()}
                isCustomer={false}
                canEdit
                editDisabledReason="You do not have edit access"
                onStartEdit={onStartEdit}
            />
        )

        await userEvent.click(screen.getByTestId('edit-private-note'))

        expect(onStartEdit).not.toHaveBeenCalled()
    })

    // Saving has to hand back both the markdown and the rich content: the thread renders rich
    // content when present, and the API only bumps the edited marker when content changes.
    it('replaces the body with the edit form and saves both content shapes', async () => {
        const onSaveEdit = jest.fn()
        const onCancelEdit = jest.fn()
        render(
            <Message
                message={privateNote()}
                isCustomer={false}
                canEdit
                isEditing
                onStartEdit={jest.fn()}
                onCancelEdit={onCancelEdit}
                onSaveEdit={onSaveEdit}
            />
        )

        expect(screen.queryByTestId('message-body')).not.toBeInTheDocument()
        expect(screen.queryByTestId('edit-private-note')).not.toBeInTheDocument()

        // Nothing typed yet, so there is nothing to save. Blocking this is what keeps an untouched
        // note from being rewritten and marked edited.
        await userEvent.click(screen.getByTestId('save-edit-private-note'))
        expect(onSaveEdit).not.toHaveBeenCalled()

        await userEvent.click(screen.getByTestId('simulate-typing'))
        await userEvent.click(screen.getByTestId('save-edit-private-note'))
        expect(onSaveEdit).toHaveBeenCalledWith('edited markdown', { type: 'doc', edited: true })

        await userEvent.click(screen.getByTestId('cancel-edit-private-note'))
        expect(onCancelEdit).toHaveBeenCalledTimes(1)
    })

    // Once a newer note supersedes this one the editor stays open so the rewrite isn't lost, but
    // saving has to be refused with the reason shown.
    it('blocks saving a superseded note but keeps the text on screen', async () => {
        const onSaveEdit = jest.fn()
        render(
            <Message
                message={privateNote()}
                isCustomer={false}
                canEdit
                isEditing
                editSaveDisabledReason="A newer private note was added"
                onStartEdit={jest.fn()}
                onCancelEdit={jest.fn()}
                onSaveEdit={onSaveEdit}
            />
        )

        await userEvent.click(screen.getByTestId('simulate-typing'))
        await userEvent.click(screen.getByTestId('save-edit-private-note'))

        expect(onSaveEdit).not.toHaveBeenCalled()
        expect(screen.getByTestId('simulate-typing')).toBeInTheDocument()
    })

    test.each<[boolean, boolean]>([
        [true, true],
        [false, false],
    ])('isEdited %s renders the edited marker: %s', (isEdited, expected) => {
        render(<Message message={privateNote({ isEdited })} isCustomer={false} />)

        expect(!!screen.queryByText('(edited)')).toBe(expected)
    })
})
