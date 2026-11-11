import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { platformAlertsDestinationsList } from '../generated/api'
import { MAX_DESTINATIONS_PER_ALERT } from './platformAlertDestinationFormat'
import { platformAlertDestinationsLogic } from './platformAlertDestinationsLogic'

jest.mock('posthog-js')
jest.mock('../generated/api', () => ({
    platformAlertsDestinationsList: jest.fn(),
    platformAlertsDestinationsCreate: jest.fn(),
    platformAlertsDestinationsDeleteCreate: jest.fn(),
}))
jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn() },
}))

const mockList = platformAlertsDestinationsList as jest.MockedFunction<typeof platformAlertsDestinationsList>

const WEBHOOK = { type: 'webhook' as const, webhookUrl: 'https://hooks.example.com/alert' }

describe('platformAlertDestinationsLogic', () => {
    beforeEach(() => {
        initKeaTests()
        mockList.mockReset()
    })

    it('stops taking pending destinations at the API limit', async () => {
        const logic = platformAlertDestinationsLogic({ alertId: null, sourceKind: 'traces' })
        logic.mount()

        for (let i = 0; i <= MAX_DESTINATIONS_PER_ALERT; i++) {
            logic.actions.setDestinationFormValues(WEBHOOK)
            logic.actions.submitDestinationForm()
            await expectLogic(logic).toFinishAllListeners()
        }

        expect(logic.values.pendingDestinations).toHaveLength(MAX_DESTINATIONS_PER_ALERT)
        expect(logic.values.atDestinationLimit).toBe(true)
    })

    it('reports a failed load rather than an empty list', async () => {
        mockList.mockRejectedValueOnce(new Error('boom'))
        const logic = platformAlertDestinationsLogic({ alertId: 'alert-1', sourceKind: 'traces' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values).toMatchObject({ destinations: null, destinationsLoadFailed: true })
    })
})
