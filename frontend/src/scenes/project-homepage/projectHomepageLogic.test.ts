import { expectLogic } from 'kea-test-utils'

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
                '/api/projects/:team/dashboards/1/': dashboardJson,
                '/api/projects/:team/insights/': { results: ['result from api'] },
                '/api/projects/:team/persons/': { results: ['result from api'] },
            },
        })
        initKeaTests()
        logic = projectHomepageLogic()
        logic.mount()
    })

    it('does not load recent insights onMount', async () => {
        await expectLogic(logic).toNotHaveDispatchedActions(['loadRecentInsights', 'loadRecentInsightsSuccess'])
    })
    it('loads persons onMount', async () => {
        await expectLogic(logic).toDispatchActions(['loadPersons', 'loadPersonsSuccess'])
    })
})
