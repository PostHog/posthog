import { MOCK_DEFAULT_BASIC_USER } from 'lib/api.mock'

import { Conversation, ConversationStatus, ConversationType } from '~/types'

import { groupConversations } from './NavTabChat'

const conversation: Conversation = {
    id: 'conversation-id',
    status: ConversationStatus.Idle,
    title: 'Testing',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    user: MOCK_DEFAULT_BASIC_USER,
    type: ConversationType.Assistant,
}

describe('groupConversations', () => {
    // A null slipping into conversation history (e.g. from an empty API response body) must not
    // crash the whole chat tab render — skip it and keep the rest of the history usable.
    it('skips null entries instead of throwing', () => {
        const groups = groupConversations([conversation, null as unknown as Conversation])

        // Assert survival of the non-null entry, not the bucket label — the label is incidental
        // to the regression and depends on the wall clock.
        expect(groups.flatMap((group) => group.items)).toEqual([conversation])
    })
})
