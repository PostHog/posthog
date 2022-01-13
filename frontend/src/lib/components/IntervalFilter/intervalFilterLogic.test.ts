import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightShortId } from '~/types'
import { MOCK_TEAM_ID, mockAPI } from 'lib/api.mock'
import { intervalFilterLogic } from 'lib/components/IntervalFilter/intervalFilterLogic'

jest.mock('lib/api')

describe('intervalFilterLogic', () => {
    let logic: ReturnType<typeof intervalFilterLogic.build>
    const props = { dashboardItemId: 'test' as InsightShortId }

    mockAPI(async ({ pathname, searchParams }) => {
        if (
            [
                `api/projects/${MOCK_TEAM_ID}/insights/path`,
                `api/projects/${MOCK_TEAM_ID}/insights/paths/`,
                `api/projects/${MOCK_TEAM_ID}/insights/trend/`,
            ].includes(pathname)
        ) {
            return { result: ['result from api'] }
        } else if (
            [`api/projects/${MOCK_TEAM_ID}/insights`].includes(pathname) ||
            String(searchParams.short_id) === 'test'
        ) {
            return { results: ['result from api'] }
        }
    })

    beforeEach(() => {
        initKeaTests()
        insightLogic(props).mount()
        logic = intervalFilterLogic(props)
        logic.mount()
    })

    describe('core assumptions', () => {
        it('mounts all sorts of logics', async () => {
            await expectLogic(logic).toMount([insightLogic(logic.props)])
        })
    })

    describe('syncs with insightLogic', () => {
        it('setInterval updates insightLogic filters', async () => {
            await expectLogic(logic, () => {
                logic.actions.setInterval('month')
            })
                .toDispatchActions([insightLogic(logic.props).actionCreators.setFilters({ interval: 'month' })])
                .toMatchValues({
                    interval: 'month',
                })
        })
    })
})
