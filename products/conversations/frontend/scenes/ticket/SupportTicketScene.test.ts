import type { Ticket } from '../../types'
import { scene, simplifiedRepliesFor } from './SupportTicketScene'

describe('SupportTicketScene', () => {
    describe('paramsToProps', () => {
        // supportTicketSceneLogic is keyed via `key((props) => props.id)`. App.tsx binds the scene's
        // logic (and the side panel context selector reads it) using whatever `paramsToProps` returns,
        // while the rendered component separately builds `supportTicketSceneLogic({ id: ticketId })`.
        // If `paramsToProps` ever stops returning `id` matching that same value, those become two
        // different logic instances: the bound one stays empty, and the ticket detail side panel's
        // access control tab silently disappears (the reported regression this test guards).
        it('keys paramsToProps by id, matching the value the component builds its logic with', () => {
            const props = scene.paramsToProps?.({
                params: { ticketId: 'ticket-123' },
                searchParams: {},
                hashParams: {},
            })
            expect(props).toEqual(expect.objectContaining({ id: 'ticket-123' }))
        })

        it('falls back to the "new" ticket key when no ticketId param is present', () => {
            const props = scene.paramsToProps?.({ params: {}, searchParams: {}, hashParams: {} })
            expect(props).toEqual(expect.objectContaining({ id: 'new' }))
        })
    })

    describe('simplifiedRepliesFor', () => {
        const slackTicket = (name: unknown): Ticket => ({
            id: 'ticket-1',
            ticket_number: 1,
            distinct_id: 'distinct-1',
            status: 'open',
            channel_source: 'slack',
            anonymous_traits: {},
            identity_verified: false,
            ai_resolved: false,
            created_at: '2026-06-12T00:00:00Z',
            updated_at: '2026-06-12T00:00:00Z',
            message_count: 1,
            last_message_at: '2026-06-12T00:00:00Z',
            last_message_text: 'Hello',
            unread_team_count: 0,
            unread_customer_count: 0,
            person: { id: 'person-1', name: '', distinct_ids: ['distinct-1'], properties: { name } },
        })

        test.each<[string, unknown, string]>([
            ['a string name as typed', 'Ada Example', 'Ada Example'],
            ['an object name as JSON text', { first: 'Ada', last: 'Example' }, '{"first":"Ada","last":"Example"}'],
        ])('shows %s', (_name, name, expected) => {
            expect(simplifiedRepliesFor(slackTicket(name), '').recipient).toBe(expected)
        })
    })
})
