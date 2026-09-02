import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import type { TeamType } from '~/types'

import { conversationsTicketsList } from 'products/conversations/frontend/generated/api'

import { supportSetupLogic } from './supportSetupLogic'

jest.mock('products/conversations/frontend/generated/api', () => ({
    conversationsTicketsList: jest.fn(),
}))

const mockTicketsList = conversationsTicketsList as jest.MockedFunction<typeof conversationsTicketsList>

function mountWithTeam(conversationsEnabled: boolean): ReturnType<typeof supportSetupLogic.build> {
    initKeaTests(true, { ...MOCK_DEFAULT_TEAM, conversations_enabled: conversationsEnabled } as TeamType)
    const logic = supportSetupLogic()
    logic.mount()
    return logic
}

// Guards the three-way ladder into the app-wide setup-status layer: no tickets and support
// off → needs-setup, on without tickets → waiting-for-data, any tickets → has-data whatever
// the toggle says. If the connect or mapping breaks, the gate shows the wrong surface.
describe('supportSetupLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it.each([
        [0, false, 'needs-setup'],
        [0, true, 'waiting-for-data'],
        [1, true, 'has-data'],
        [42, true, 'has-data'],
        // A team that switched support off keeps its tickets, and this list is the only
        // place to read them, so the history has to outrank the toggle.
        [42, false, 'has-data'],
    ])('pushes %i tickets with support enabled=%s as status %s', async (count, enabled, expected) => {
        mockTicketsList.mockResolvedValue({ count, next: null, previous: null, results: [] })
        const logic = mountWithTeam(enabled)
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.CONVERSATIONS }).values.status).toBe(expected)
    })

    it('fails open to unknown when the count query fails before any answer', async () => {
        mockTicketsList.mockRejectedValue(new Error('network down'))
        const logic = mountWithTeam(true)
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.CONVERSATIONS }).values.status).toBe('unknown')
    })
})
