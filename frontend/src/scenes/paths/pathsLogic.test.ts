import { mockAPI } from 'lib/api.mock'
import { expectLogic, initKeaTestLogic } from '~/test/kea-test-utils'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

jest.mock('lib/api')

describe('pathsLogic', () => {
    let logic: ReturnType<typeof pathsLogic.build>

    mockAPI(async ({ pathname, searchParams }) => {
        if (pathname === '_preflight/') {
            return { is_clickhouse_enabled: true }
        } else if (pathname === 'api/users/@me/') {
            return { organization: {}, team: { ingested_event: true, completed_snippet_onboarding: true } }
        } else if (
            [
                'api/action/',
                'api/projects/@current/event_definitions/',
                'api/users/@me/',
                'api/dashboard',
                'api/insight',
            ].includes(pathname)
        ) {
            return { results: [] }
        } else if (['api/insight/paths/'].includes(pathname)) {
            return { result: ['result from api'] }
        } else {
            throw new Error(`Unmocked fetch to: ${pathname} with params: ${JSON.stringify(searchParams)}`)
        }
    })

    describe('syncs with insightLogic', () => {
        const props = { dashboardItemId: 123 }
        initKeaTestLogic({
            logic: pathsLogic,
            props,
            onLogic: (l) => (logic = l),
        })

        it('setFilter calls insightLogic.setFilters', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilter({
                    step_limit: 999,
                })
            })
                .toDispatchActions([
                    (action) =>
                        action.type === insightLogic(props).actionTypes.setFilters &&
                        action.payload.filters?.step_limit === 999,
                ])
                .toMatchValues(logic, {
                    filter: expect.objectContaining({
                        step_limit: 999,
                    }),
                })
                .toMatchValues(insightLogic(props), {
                    filters: expect.objectContaining({
                        step_limit: 999,
                    }),
                })
        })

        it('insightLogic.setFilters updates filter', async () => {
            await expectLogic(logic, () => {
                insightLogic(props).actions.setFilters({
                    step_limit: 999,
                })
            })
                .toMatchValues(logic, {
                    filter: expect.objectContaining({
                        step_limit: 999,
                    }),
                })
                .toMatchValues(insightLogic(props), {
                    filters: expect.objectContaining({
                        step_limit: 999,
                    }),
                })
        })
    })
})
