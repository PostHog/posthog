import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { Ticket } from '../../types'
import { supportTicketSceneLogic } from './supportTicketSceneLogic'

const TICKET_ID = '11111111-1111-1111-1111-111111111111'

const RELATED_URL = '/api/projects/:project_id/conversations/tickets/:id/related/'

const mockTicket = { id: TICKET_ID, ticket_number: 42, status: 'open' } as Ticket

const relatedResults = [
    {
        source: 'conversations',
        id: '22222222-2222-2222-2222-222222222222',
        title: 'Billing question',
        status: 'resolved',
        ticket_number: 7,
        last_activity: '2024-01-01T00:00:00Z',
    },
    {
        source: 'zendesk',
        id: 'zd-99',
        title: 'Login broken',
        status: 'open',
        url: 'https://example.zendesk.com/agent/tickets/99',
    },
]

describe('supportTicketSceneLogic related tickets', () => {
    let logic: ReturnType<typeof supportTicketSceneLogic.build>

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.PRODUCT_SUPPORT_RELATED_TICKETS]: true })
    })

    afterEach(() => {
        logic?.unmount()
    })

    function mountWithTicket(): void {
        logic = supportTicketSceneLogic({ id: TICKET_ID })
        logic.mount()
        logic.actions.setTicket(mockTicket)
    }

    it('loads related tickets into the relatedTickets value', async () => {
        useMocks({ get: { [RELATED_URL]: () => [200, relatedResults] } })

        mountWithTicket()
        logic.actions.loadRelatedTickets()

        await expectLogic(logic)
            .toDispatchActions(['loadRelatedTickets', 'loadRelatedTicketsSuccess'])
            .toMatchValues({ relatedTickets: relatedResults, relatedTicketsLoading: false })
    })

    it('starts in a loading state while the request is in flight', async () => {
        useMocks({ get: { [RELATED_URL]: () => [200, relatedResults] } })

        mountWithTicket()
        logic.actions.loadRelatedTickets()
        expect(logic.values.relatedTicketsLoading).toBe(true)

        await expectLogic(logic).toDispatchActions(['loadRelatedTicketsSuccess'])
    })

    it('falls back to an empty list when the request fails', async () => {
        useMocks({ get: { [RELATED_URL]: () => [500, { detail: 'boom' }] } })

        mountWithTicket()
        logic.actions.loadRelatedTickets()

        await expectLogic(logic)
            .toDispatchActions(['loadRelatedTickets', 'loadRelatedTicketsSuccess'])
            .toMatchValues({ relatedTickets: [], relatedTicketsLoading: false })
    })

    it('returns an empty list without calling the API when no ticket is loaded', async () => {
        const relatedMock = jest.fn(() => [200, relatedResults])
        useMocks({ get: { [RELATED_URL]: relatedMock } })

        logic = supportTicketSceneLogic({ id: TICKET_ID })
        logic.mount()
        logic.actions.loadRelatedTickets()

        await expectLogic(logic).toDispatchActions(['loadRelatedTicketsSuccess']).toMatchValues({ relatedTickets: [] })
        expect(relatedMock).not.toHaveBeenCalled()
    })
})
