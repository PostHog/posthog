import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { DashboardType } from '~/types'

import _dashboardJson from '../dashboard/__mocks__/dashboard.json'
import { projectHomepageLogic } from './projectHomepageLogic'

const dashboardJson = _dashboardJson as any as DashboardType

describe('projectHomepageLogic', () => {
    let logic: ReturnType<typeof projectHomepageLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/dashboards/1/': dashboardJson,
                '/api/environments/:team_id/insights/': { results: ['result from api'] },
                '/api/environments/:team_id/persons/': { results: ['result from api'] },
            },
        })
        initKeaTests()
        logic = projectHomepageLogic()
        logic.mount()
    })

    it('does not load recent insights onMount', async () => {
        await expectLogic(logic).toNotHaveDispatchedActions(['loadRecentInsights', 'loadRecentInsightsSuccess'])
    })

    it.each([
        [true, '/home/reports/report-1'],
        [false, '/inbox/reports/report-1'],
    ])('waits for the flags before it leaves a Today report (today on: %s)', async (todayOn, expectedPath) => {
        router.actions.push(urls.todayReport('report-1'))
        expect(router.values.location.pathname).toContain('/home/reports/report-1')

        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TODAY_RAIL_NAV]: todayOn })

        expect(router.values.location.pathname).toContain(expectedPath)
    })
})
