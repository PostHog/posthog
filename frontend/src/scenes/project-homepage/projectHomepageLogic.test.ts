import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { DashboardType } from '~/types'

import _dashboardJson from 'products/dashboards/frontend/__mocks__/dashboard.json'

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

    it('sends a Today report link to the inbox report page, with a way back to Home', () => {
        router.actions.push(urls.todayReport('report-1'), { link_source: 'today' })

        expect(router.values.location.pathname).toContain('/inbox/reports/report-1')
        expect(router.values.searchParams).toEqual({ back: '/home', link_source: 'today' })
    })

    it.each([
        [true, '/home/reports/sample-pr'],
        [false, '/inbox/reports/sample-pr'],
    ])('waits for the flags before it leaves a sample report (today on: %s)', async (todayOn, expectedPath) => {
        router.actions.push(urls.todayReport('sample-pr'))
        expect(router.values.location.pathname).toContain('/home/reports/sample-pr')

        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TODAY_RAIL_NAV]: todayOn })

        expect(router.values.location.pathname).toContain(expectedPath)
    })
})
