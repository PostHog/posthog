import { cleanup, render } from '@testing-library/react'

import { ConversationTurn } from '../types'
import { Thread } from './Thread'

const internalOnlyTurn: ConversationTurn = {
    id: 'trace-1',
    timestamp: '2026-09-01T10:15:00Z',
    waitMs: null,
    error: null,
    input: {
        kind: 'messages',
        messages: [
            {
                id: 'gen-1-in-0',
                role: 'assistant',
                parts: [{ kind: 'text', text: 'Checking the seat history.' }],
                isInternal: true,
                sourceNodeId: 'gen-1',
            },
        ],
    },
    output: { kind: 'messages', messages: [] },
}

describe('Thread', () => {
    afterEach(cleanup)

    it('says the conversation is empty when "conversation only" hides every message', () => {
        const { getByText } = render(
            <Thread
                conversation={{ status: 'ready', turns: [internalOnlyTurn], activeTurnId: null }}
                onSelectMessage={() => {}}
                conversationOnly
                emptyMessage="No conversation to show."
            />
        )

        expect(getByText('No conversation to show.')).toBeTruthy()
    })
})
