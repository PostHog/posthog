import { expectLogic } from 'kea-test-utils'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { webAnalyticsHealthLogic } from './webAnalyticsHealthLogic'

describe('webAnalyticsHealthLogic', () => {
    let logic: ReturnType<typeof webAnalyticsHealthLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/health_issues/': () => [
                    200,
                    { results: [{ kind: 'no_live_events', severity: 'critical' }] },
                ],
            },
        })
        initKeaTests()
        eventUsageLogic.mount()
        logic = webAnalyticsHealthLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('reports the health status once per change, not once per poll', async () => {
        await expectLogic(logic).toDispatchActions(['loadHealthIssuesSuccess', 'reportWebAnalyticsHealthStatus'])

        await expectLogic(logic, () => {
            logic.actions.loadHealthIssues()
        })
            .toDispatchActions(['loadHealthIssuesSuccess'])
            .toNotHaveDispatchedActions(['reportWebAnalyticsHealthStatus'])
    })
})
