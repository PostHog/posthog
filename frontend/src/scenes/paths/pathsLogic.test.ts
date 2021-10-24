import { defaultAPIMocks, mockAPI, MOCK_TEAM_ID } from 'lib/api.mock'
import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

jest.mock('lib/api')

describe('pathsLogic', () => {
    let logic: ReturnType<typeof pathsLogic.build>

    mockAPI(async (url) => {
        const { pathname } = url
        if (`api/projects/${MOCK_TEAM_ID}/insights/paths/` === pathname) {
            return { result: ['result from api'] }
        }
        return defaultAPIMocks(url)
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
                    insight: 'PATHS',
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
                    insight: 'PATHS',
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
