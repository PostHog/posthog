import { expectLogic } from 'kea-test-utils'

import { ApiConfig } from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ProjectType } from '~/types'

import { INBOX_FLAT_TAB_LIST_PARAMS, reportListLogic } from './reportListLogic'

describe('reportListLogic', () => {
    let logic: ReturnType<typeof reportListLogic.build>

    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports': () => [200, { count: 3, results: [], next: null }],
                // Connecting inboxFiltersLogic preloads the reviewer roster on mount.
                '/api/projects/:team_id/signals/reports/available_reviewers': () => [200, {}],
            },
        })
        logic = reportListLogic({ tabKey: 'reports', listParams: INBOX_FLAT_TAB_LIST_PARAMS.reports })
    })

    afterEach(() => {
        logic.unmount()
    })

    it('loads the count on mount once the project id is known', async () => {
        await expectLogic(logic, () => {
            logic.mount()
        })
            .toDispatchActions(['loadCount', 'loadCountSuccess'])
            .toMatchValues({ count: 3 })
    })

    it('skips the count request on mount while the project id is unknown', async () => {
        // Regression: `loadCount` → `api.signalReports.list` routes through
        // `projectsDetail(getCurrentProjectId())`, which throws `Project ID is not known.` when
        // the id has not been seeded yet (early app init / OAuth bootstrap). The unguarded loader
        // surfaced that as an unhandled rejection through kea-loaders.
        ApiConfig.setCurrentProjectId(null as unknown as ProjectType['id'])

        await expectLogic(logic, () => {
            logic.mount()
        }).toNotHaveDispatchedActions(['loadCount'])
    })
})
