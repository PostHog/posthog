import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { platformAlertsList, platformAlertsPartialUpdate } from './generated/api'
import { PlatformAlertConfigurationApi } from './generated/api.schemas'
import { PlatformAlertListLogicProps, platformAlertListLogic } from './platformAlertListLogic'

jest.mock('posthog-js')
jest.mock('./generated/api', () => ({
    platformAlertsList: jest.fn(),
    platformAlertsPartialUpdate: jest.fn(),
    platformAlertsDestroy: jest.fn(),
}))
jest.mock('@posthog/lemon-ui', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn() },
}))

const mockList = platformAlertsList as jest.MockedFunction<typeof platformAlertsList>
const mockPartialUpdate = platformAlertsPartialUpdate as jest.MockedFunction<typeof platformAlertsPartialUpdate>

const ALERT = { id: 'alert-1', name: 'Slow checkout', enabled: true } as PlatformAlertConfigurationApi

describe('platformAlertListLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mockList.mockResolvedValue({ results: [ALERT] } as Awaited<ReturnType<typeof platformAlertsList>>)
    })

    test.each(['traces', 'metrics'] as const)(
        'lists and toggles only %s alerts',
        async (sourceKind: PlatformAlertListLogicProps['sourceKind']) => {
            const logic = platformAlertListLogic({ sourceKind, analyticsEvents: { enabledToggled: 'toggled' } })
            logic.mount()
            await expectLogic(logic)
                .toFinishAllListeners()
                .toMatchValues({ alerts: [ALERT], alertsLoaded: true })
            expect(mockList).toHaveBeenCalledWith(
                expect.any(String),
                expect.objectContaining({ source_kind: sourceKind })
            )

            mockPartialUpdate.mockResolvedValue(ALERT)
            logic.actions.toggleAlertEnabled(ALERT)
            await expectLogic(logic).toFinishAllListeners()
            expect(mockPartialUpdate).toHaveBeenCalledWith(expect.any(String), ALERT.id, {
                source_kind: sourceKind,
                enabled: false,
            })
        }
    )

    it('clears the toggling state when the update fails', async () => {
        const logic = platformAlertListLogic({ sourceKind: 'traces', analyticsEvents: { enabledToggled: 'toggled' } })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        let rejectUpdate: (error: Error) => void = () => {}
        mockPartialUpdate.mockReturnValue(new Promise((_, reject) => (rejectUpdate = reject)))
        logic.actions.toggleAlertEnabled(ALERT)
        expect(logic.values.togglingAlertIds).toEqual(new Set([ALERT.id]))

        rejectUpdate(new Error('boom'))
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.togglingAlertIds).toEqual(new Set())
    })
})
