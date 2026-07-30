import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { webAnalyticsHealthLogic } from './webAnalyticsHealthLogic'

const ISSUES_URL = '/api/projects/:team_id/health_issues/'
const REFRESH_URL = '/api/projects/:team_id/health_issues/refresh/'

const issue = (kind: string): Record<string, unknown> => ({
    id: `id-${kind}`,
    kind,
    severity: 'critical',
    status: 'active',
    dismissed: false,
    payload: {},
})

describe('webAnalyticsHealthLogic', () => {
    let logic: ReturnType<typeof webAnalyticsHealthLogic.build>
    let refreshBodies: unknown[]

    const useHealthMocks = (issuesHandler: () => [number, unknown]): void => {
        refreshBodies = []
        useMocks({
            get: { [ISSUES_URL]: issuesHandler },
            post: {
                [REFRESH_URL]: async ({ request }) => {
                    refreshBodies.push(await request.json().catch(() => null))
                    return [202, { scheduled_kinds: ['no_live_events'], kinds_failed: [], team_id: 1 }]
                },
            },
        })
        logic = webAnalyticsHealthLogic()
        logic.mount()
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('re-runs only the install check, once, when it is failing', async () => {
        useHealthMocks(() => [200, { results: [issue('no_live_events')] }])

        await expectLogic(logic)
            .toDispatchActions(['loadHealthIssuesSuccess', 'refreshHealthChecks'])
            .toMatchValues({ nextRefreshAvailableAt: null })

        await expectLogic(logic, () => {
            logic.actions.loadHealthIssues()
        }).toDispatchActions(['loadHealthIssuesSuccess'])

        expect(refreshBodies).toEqual([{ kinds: ['no_live_events'] }])
    })

    it('does not touch the refresh endpoint when the install check passes', async () => {
        useHealthMocks(() => [200, { results: [issue('web_vitals')] }])

        await expectLogic(logic).toDispatchActions(['loadHealthIssuesSuccess']).toFinishAllListeners()

        expect(refreshBodies).toEqual([])
    })

    it('reports checks as unavailable rather than passing when loading them fails', async () => {
        useHealthMocks(() => [500, { detail: 'nope' }])

        await expectLogic(logic).toDispatchActions(['loadHealthIssuesFailure']).toMatchValues({
            checksUnavailable: true,
        })
    })
})
