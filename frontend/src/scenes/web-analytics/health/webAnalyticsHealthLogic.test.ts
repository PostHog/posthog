import { expectLogic } from 'kea-test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HealthCheck } from './healthCheckTypes'
import { webAnalyticsHealthLogic } from './webAnalyticsHealthLogic'

describe('webAnalyticsHealthLogic', () => {
    let logic: ReturnType<typeof webAnalyticsHealthLogic.build>

    beforeEach(() => {
        silenceKeaLoadersErrors()
        initKeaTests()
        featureFlagLogic.mount()
        teamLogic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        resumeKeaLoadersErrors()
    })

    it('fails closed when the health_issues fetch errors and there is no data', async () => {
        // Regression guard: a failed fetch used to leave every check on the no-issue branch, so
        // the page claimed a healthy setup during an outage. It must render "couldn't check".
        useMocks({
            get: {
                '/api/projects/:team_id/health_issues/': () => [500, { detail: 'A server error occurred' }],
            },
        })

        logic = webAnalyticsHealthLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadHealthIssuesFailure'])

        const { allChecks, overallHealthStatus, hasUrgentIssues } = logic.values
        expect(allChecks.every((check: HealthCheck) => check.status === 'unknown')).toBe(true)
        expect(overallHealthStatus.status).toBe('unknown')
        expect(overallHealthStatus.passedCount).toBe(0)
        // A failed fetch is not a confirmed urgent failure, so the red tab badge must stay off.
        expect(hasUrgentIssues).toBe(false)
    })
})
