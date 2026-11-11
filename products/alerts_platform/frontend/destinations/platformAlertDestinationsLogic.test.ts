import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import { platformAlertsDestinationsList } from '../generated/api'
import { PlatformAlertDestinationTypeEnumApi } from '../generated/api.schemas'
import { MAX_DESTINATIONS_PER_ALERT } from './platformAlertDestinations'
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

describe('platformAlertDestinationsLogic', () => {
    let logic: ReturnType<typeof platformAlertDestinationsLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockList.mockReset()
        logic = platformAlertDestinationsLogic({ sourceKind: 'traces' })
        logic.mount()
    })

    it('stops taking pending destinations at the API limit', async () => {
        logic.actions.setSelectedType(PlatformAlertDestinationTypeEnumApi.Webhook)
        for (let i = 0; i <= MAX_DESTINATIONS_PER_ALERT; i++) {
            logic.actions.setWebhookUrl('https://hooks.example.com/alert')
            logic.actions.addSelectedDestination()
            await expectLogic(logic).toFinishAllListeners()
        }

        expect(logic.values.pendingDestinations).toHaveLength(MAX_DESTINATIONS_PER_ALERT)
        expect(logic.values.addDisabledReason).toContain(`at most ${MAX_DESTINATIONS_PER_ALERT}`)
    })

    it('queues a PagerDuty destination with its incident settings', async () => {
        logic.actions.setSelectedType(PlatformAlertDestinationTypeEnumApi.Pagerduty)
        logic.actions.setPagerDutyRoutingKey(' abcdefghijklmnopqrstuvwxyz012345 ')
        logic.actions.setPagerDutySeverity('warning')
        logic.actions.setPagerDutyRegion('eu')
        logic.actions.addSelectedDestination()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.pendingDestinations).toEqual([
            {
                type: 'pagerduty',
                pagerduty_routing_key: 'abcdefghijklmnopqrstuvwxyz012345',
                pagerduty_severity: 'warning',
                pagerduty_region: 'eu',
            },
        ])
    })

    it.each([
        [PlatformAlertDestinationTypeEnumApi.Discord, 'https://example.com/hook', 'Discord webhook URL'],
        [PlatformAlertDestinationTypeEnumApi.Teams, 'https://example.com/hook', 'Teams workflow'],
        [PlatformAlertDestinationTypeEnumApi.Webhook, 'http://example.com/hook', 'https URL'],
        [PlatformAlertDestinationTypeEnumApi.Discord, 'https://discord.com/api/webhooks/1/abc', undefined],
        [
            PlatformAlertDestinationTypeEnumApi.Teams,
            'https://prod-01.westus.logic.azure.com/workflows/abc/triggers/manual/paths/invoke?sig=x',
            undefined,
        ],
    ])('checks a %s URL %s as the API would', (type, url, expectedError) => {
        logic.actions.setSelectedType(type)
        logic.actions.setWebhookUrl(url)

        expect(logic.values.addDisabledReason ?? null).toEqual(
            expectedError ? expect.stringContaining(expectedError) : null
        )
    })

    it('reports a failed load rather than an empty list', async () => {
        silenceKeaLoadersErrors()
        mockList.mockRejectedValueOnce(new Error('boom'))
        const saved = platformAlertDestinationsLogic({ alertId: 'alert-1', sourceKind: 'traces' })
        saved.mount()
        await expectLogic(saved).toFinishAllListeners()
        resumeKeaLoadersErrors()

        expect(saved.values).toMatchObject({ destinations: [], destinationsLoadFailed: true })
    })
})
