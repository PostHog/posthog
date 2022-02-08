import { mockAPI, MOCK_TEAM_ID } from 'lib/api.mock'
import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { InsightShortId } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'

jest.mock('lib/api')

const Insight123 = '123' as InsightShortId

describe('trendsLogic', () => {
    let logic: ReturnType<typeof trendsLogic.build>

    mockAPI(async ({ pathname, searchParams }) => {
        if (pathname === `api/projects/${MOCK_TEAM_ID}/insights` || String(searchParams.short_id) === Insight123) {
            return { results: ['result from api'] }
        } else if (
            [`api/projects/${MOCK_TEAM_ID}/insights/123`, `api/projects/${MOCK_TEAM_ID}/insights/trend/`].includes(
                pathname
            )
        ) {
            return { result: ['result from api'] }
        }
    })

    describe('core assumptions', () => {
        initKeaTestLogic({
            logic: trendsLogic,
            props: { dashboardItemId: undefined },
            onLogic: (l) => (logic = l),
        })

        it('loads results on mount', async () => {
            await expectLogic(logic).toDispatchActions([
                insightLogic({ dashboardItemId: undefined }).actionTypes.loadResults,
            ])
        })
    })

    describe('reducers', () => {
        initKeaTestLogic({
            logic: trendsLogic,
            props: { dashboardItemId: undefined },
            onLogic: (l) => (logic = l),
        })
    })

    describe('syncs with insightLogic', () => {
        const props = { dashboardItemId: Insight123 }
        initKeaTestLogic({
            logic: trendsLogic,
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

        it('insightLogic.setFilters updates filters', async () => {
            await expectLogic(logic, () => {
                insightLogic(props).actions.setFilters({ events: [{ id: 42 }] })
            })
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
