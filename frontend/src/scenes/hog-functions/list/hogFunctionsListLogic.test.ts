import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { HogFunctionType } from '~/types'

import { hogFunctionsListLogic } from './hogFunctionsListLogic'

const makeNotification = (id: string, eventId: string): HogFunctionType =>
    ({
        id,
        name: id,
        type: 'internal_destination',
        enabled: true,
        hog: '',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        filters: { events: [{ id: eventId, type: 'events' }] },
    }) as HogFunctionType

const INSIGHT_ALERT = makeNotification('insight-alert', '$insight_alert_firing')
const ERROR_TRACKING = makeNotification('error-tracking', '$error_tracking_issue_created')

describe('hogFunctionsListLogic', () => {
    let logic: ReturnType<typeof hogFunctionsListLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_functions/': {
                    count: 2,
                    next: null,
                    results: [INSIGHT_ALERT, ERROR_TRACKING],
                },
            },
        })
        initKeaTests()
        logic = hogFunctionsListLogic({ type: 'internal_destination' })
        logic.mount()
        logic.actions.loadHogFunctions()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('filters notifications by the product that sends them', async () => {
        await expectLogic(logic).toMatchValues({
            filteredHogFunctions: [INSIGHT_ALERT, ERROR_TRACKING],
            notificationSources: ['insight-alerts', 'error-tracking'],
        })

        logic.actions.setFilters({ notificationSource: 'error-tracking' })

        await expectLogic(logic).toMatchValues({
            filteredHogFunctions: [ERROR_TRACKING],
            hiddenHogFunctions: [INSIGHT_ALERT],
        })
    })

    it.each([
        ['drops the row when the API accepts the delete', false, [INSIGHT_ALERT]],
        ['keeps the row when the API refuses the delete', true, [INSIGHT_ALERT, ERROR_TRACKING]],
    ])('%s', async (_, refused, expected) => {
        useMocks({
            patch: {
                '/api/projects/:team_id/hog_functions/:id': refused
                    ? () => [400, { detail: 'Alert notification destinations are managed through the alert API.' }]
                    : { ...ERROR_TRACKING, deleted: true },
            },
        })

        logic.actions.deleteHogFunction(ERROR_TRACKING)
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic).toMatchValues({ hogFunctions: expected })
    })
})
