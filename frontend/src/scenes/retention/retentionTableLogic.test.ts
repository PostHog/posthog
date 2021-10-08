import { mockAPI } from 'lib/api.mock'
import { expectLogic, initKeaTestLogic } from '~/test/kea-test-utils'
import { retentionTableLogic } from 'scenes/retention/retentionTableLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

jest.mock('lib/api')

describe('retentionTableLogic', () => {
    let logic: ReturnType<typeof retentionTableLogic.build>

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
        } else if (['api/insight/retention/'].includes(pathname)) {
            return { result: ['result from api'] }
        } else {
            throw new Error(`Unmocked fetch to: ${pathname} with params: ${JSON.stringify(searchParams)}`)
        }
    })

    describe('syncs with insightLogic', () => {
        const props = { dashboardItemId: 123 }
        initKeaTestLogic({
            logic: retentionTableLogic,
            props,
            onLogic: (l) => (logic = l),
        })

        it('setFilters calls insightLogic.setFilters', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ events: [{ id: 42 }] })
            })
                .toDispatchActions([
                    (action) =>
                        action.type === insightLogic(props).actionTypes.setFilters &&
                        action.payload.filters?.events?.[0]?.id === 42,
                ])
                .toMatchValues(logic, {
                    filters: expect.objectContaining({
                        events: [{ id: 42 }],
                    }),
                })
                .toMatchValues(insightLogic(props), {
                    filters: expect.objectContaining({
                        events: [{ id: 42 }],
                    }),
                })
        })
    })
})
