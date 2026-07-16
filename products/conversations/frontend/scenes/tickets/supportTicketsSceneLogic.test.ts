import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import type { Ticket } from '../../types'
import { supportTicketsSceneLogic } from './supportTicketsSceneLogic'

function makeTicket(id: string, userAccessLevel?: AccessControlLevel): Ticket {
    return {
        id,
        ticket_number: 1,
        distinct_id: `distinct-${id}`,
        status: 'open',
        channel_source: 'email',
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
        user_access_level: userAccessLevel,
    }
}

describe('supportTicketsSceneLogic', () => {
    let logic: ReturnType<typeof supportTicketsSceneLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/tickets/': () => [200, { results: [], count: 0 }],
            },
        })
        initKeaTests()
        logic = supportTicketsSceneLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    // Regression: bulk status updates must only ever be sent for tickets the caller can edit.
    // The backend already enforces this (silently skipping non-editable IDs), but a selection
    // mixing editable and view-only tickets should be filtered client-side too, not just relayed
    // wholesale to the API.
    it('filters out tickets the user cannot edit at the object level', () => {
        const editable = makeTicket('editable', AccessControlLevel.Editor)
        const viewerOnly = makeTicket('viewer-only', AccessControlLevel.Viewer)
        const noAccess = makeTicket('no-access', AccessControlLevel.None)
        const unset = makeTicket('unset')

        expectLogic(logic, () => {
            logic.actions.setTickets([editable, viewerOnly, noAccess, unset])
            logic.actions.setSelectedTicketIds([editable.id, viewerOnly.id, noAccess.id, unset.id])
        }).toMatchValues({
            editableSelectedTicketIds: [editable.id, unset.id],
        })
    })

    it('includes every selected ticket when none are access-restricted', () => {
        const a = makeTicket('a', AccessControlLevel.Editor)
        const b = makeTicket('b', AccessControlLevel.Manager)

        expectLogic(logic, () => {
            logic.actions.setTickets([a, b])
            logic.actions.setSelectedTicketIds([a.id, b.id])
        }).toMatchValues({
            editableSelectedTicketIds: [a.id, b.id],
        })
    })
})
