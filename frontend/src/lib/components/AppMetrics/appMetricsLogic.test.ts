import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { appMetricsLogic } from './appMetricsLogic'

describe('appMetricsLogic', () => {
    let logic: ReturnType<typeof appMetricsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = appMetricsLogic({
            logicKey: 'test',
            loadOnMount: false,
            forceParams: {
                appSource: 'hog_function',
                appSourceId: 'abc',
                metricName: ['succeeded'],
                breakdownBy: 'metric_name',
            },
        })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('renders a 403 as an error state instead of reporting it to error tracking', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': () => [
                    403,
                    { detail: 'You do not have access to this environment', code: 'permission_denied' },
                ],
            },
        })
        const captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)

        await expectLogic(logic, () => {
            logic.actions.loadAppMetricsTrends()
        })
            .toDispatchActions(['setAppMetricsTrendsError'])
            .toMatchValues({
                appMetricsTrends: null,
                appMetricsTrendsError: 'You do not have access to this environment',
            })

        // The rejection is caught in the loader, so kea-loaders never runs its onFailure path.
        expect(captureExceptionSpy).not.toHaveBeenCalled()

        captureExceptionSpy.mockRestore()
    })

    it('drops a failing previous-period series quietly without an error banner', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': () => [403, { detail: 'nope' }],
            },
        })

        await expectLogic(logic, () => {
            logic.actions.loadAppMetricsTrendsPreviousPeriod()
        })
            .toDispatchActions(['loadAppMetricsTrendsPreviousPeriodSuccess'])
            .toMatchValues({
                appMetricsTrendsPreviousPeriod: null,
                appMetricsTrendsError: null,
            })
    })
})
