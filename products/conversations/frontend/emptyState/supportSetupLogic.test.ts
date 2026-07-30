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

// Guards the three-way ladder into the app-wide setup-status layer: disabled team →
// needs-setup, enabled without tickets → waiting-for-data, tickets → has-data. If the
// connect or mapping breaks, the scene empty-state gate shows the wrong surface.
describe('supportSetupLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('pushes needs-setup without querying tickets when conversations are disabled', async () => {
        const logic = mountWithTeam(false)
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.CONVERSATIONS }).values.status).toBe('needs-setup')
        expect(mockTicketsList).not.toHaveBeenCalled()
    })

    it.each([
        [0, 'waiting-for-data'],
        [1, 'has-data'],
        [42, 'has-data'],
    ])('pushes a ticket count of %i as status %s when conversations are enabled', async (count, expected) => {
        mockTicketsList.mockResolvedValue({ count, next: null, previous: null, results: [] })
        const logic = mountWithTeam(true)
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
