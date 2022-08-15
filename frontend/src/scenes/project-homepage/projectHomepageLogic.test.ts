import { expectLogic } from 'kea-test-utils'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { DashboardType } from '~/types'
import { projectHomepageLogic } from './projectHomepageLogic'
import _dashboardJson from '../dashboard/__mocks__/dashboard.json'

const dashboardJson = _dashboardJson as any as DashboardType

describe('projectHomepageLogic', () => {
    let logic: ReturnType<typeof projectHomepageLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/dashboards/1/': dashboardJson,
                '/api/projects/:team/insights/': { results: ['result from api'] },
                '/api/person/': { results: ['result from api'] },
            },
        })
        initKeaTests()
        logic = projectHomepageLogic()
        logic.mount()
    })

    it('loads recent insights onMount', async () => {
        await expectLogic(logic).toDispatchActions(['loadRecentInsights', 'loadRecentInsightsSuccess'])
    })
    it('loads persons onMount', async () => {
        await expectLogic(logic).toDispatchActions(['loadPersons', 'loadPersonsSuccess'])
    })
})
