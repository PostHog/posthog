import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightShortId } from '~/types'
import { intervalFilterLogic } from 'lib/components/IntervalFilter/intervalFilterLogic'
import { useMocks } from '~/mocks/jest'

describe('intervalFilterLogic', () => {
    let logic: ReturnType<typeof intervalFilterLogic.build>
    const props = { dashboardItemId: 'test' as InsightShortId }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/insights/path': { result: ['result from api'] },
                '/api/projects/:team/insights/paths/': { result: ['result from api'] },
                '/api/projects/:team/insights/trend/': { result: ['result from api'] },
                '/api/projects/${MOCK_TEAM_ID}/insights': { results: ['result from api'] },
            },
        })
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
