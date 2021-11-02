import { defaultAPIMocks, mockAPI, MOCK_TEAM_ID } from 'lib/api.mock'
import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { retentionTableLogic } from 'scenes/retention/retentionTableLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

jest.mock('lib/api')

describe('retentionTableLogic', () => {
    let logic: ReturnType<typeof retentionTableLogic.build>

    mockAPI(async (url) => {
        const { pathname } = url
        if ([`api/projects/${MOCK_TEAM_ID}/insights/`, `api/projects/${MOCK_TEAM_ID}/actions/`].includes(pathname)) {
            return { results: [] }
        } else if (pathname === `api/projects/${MOCK_TEAM_ID}/insights/retention/`) {
            return { result: ['result from api'] }
        }
        return defaultAPIMocks(url)
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
                logic.actions.setFilters({ insight: 'RETENTION', period: 'Week' })
            })
                .toDispatchActions([
                    (action) =>
                        action.type === insightLogic(props).actionTypes.setFilters &&
                        action.payload.filters?.period === 'Week',
                ])
                .toMatchValues(logic, {
                    filters: expect.objectContaining({
                        period: 'Week',
                    }),
                })
                .toMatchValues(insightLogic(props), {
                    filters: expect.objectContaining({
                        period: 'Week',
                    }),
                })
        })

        it('insightLogic.setFilters updates filters', async () => {
            await expectLogic(logic, () => {
                insightLogic(props).actions.setFilters({ insight: 'RETENTION', period: 'Week' })
            })
                .toMatchValues(logic, {
                    filters: expect.objectContaining({
                        period: 'Week',
                    }),
                })
                .toMatchValues(insightLogic(props), {
                    filters: expect.objectContaining({
                        period: 'Week',
                    }),
                })
        })
    })
})
