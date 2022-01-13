import { compareFilterLogic } from 'lib/components/CompareFilter/compareFilterLogic'
import { initKeaTests } from '~/test/init'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { expectLogic } from 'kea-test-utils'
import { InsightLogicProps, InsightShortId, InsightType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'

describe('compareFilterLogic', () => {
    let logic: ReturnType<typeof compareFilterLogic.build>

    beforeEach(() => {
        initKeaTests()
        const logicProps: InsightLogicProps = { dashboardItemId: '1' as InsightShortId, syncWithUrl: true }
        insightLogic(logicProps).mount()
        logic = compareFilterLogic(logicProps)
        logic.mount()
    })

    describe('keeps compare updated to router', () => {
        it('default', async () => {
            router.actions.push(urls.insightView('1' as InsightShortId, {}))
            await expectLogic(router).toDispatchActions(['push', 'locationChanged']).toMatchValues(logic, {
                compare: false,
                disabled: false,
            })
        })
        it('initial compare value', async () => {
            router.actions.push(urls.insightView('1' as InsightShortId, { compare: true }))
            await expectLogic(logic).toMatchValues({
                compare: true,
                disabled: false,
            })
        })
        it('disable for lifecycle insight', async () => {
            router.actions.push(urls.insightView('1' as InsightShortId, { insight: InsightType.LIFECYCLE }))
            await expectLogic(logic).toMatchValues({
                disabled: true,
            })
        })
        it('disable for `all time` date filter', async () => {
            router.actions.push(urls.insightView('1' as InsightShortId, { date_from: 'all' }))
            await expectLogic(logic).toMatchValues({
                disabled: true,
            })
        })
    })
})
