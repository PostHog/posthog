import { compareFilterLogic } from 'lib/components/CompareFilter/compareFilterLogic'
import { initKeaTestLogic } from '~/test/init'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { expectLogic } from 'kea-test-utils'
import { InsightShortId, InsightType } from '~/types'

describe('compareFilterLogic', () => {
    let logic: ReturnType<typeof compareFilterLogic.build>

    initKeaTestLogic({
        logic: compareFilterLogic,
        props: {},
        onLogic: (l) => (logic = l),
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
            await expectLogic(router)
                .toDispatchActions(['push', 'locationChanged'])
                .toDispatchActions([logic.actionCreators.setCompare(true)])
                .toMatchValues(logic, {
                    compare: true,
                    disabled: false,
                })
        })
        it('disable for lifecycle insight', async () => {
            router.actions.push(urls.insightView('1' as InsightShortId, { insight: InsightType.LIFECYCLE }))
            await expectLogic(router)
                .toDispatchActions(['push', 'locationChanged'])
                .toDispatchActions([logic.actionCreators.setDisabled(true)])
                .toMatchValues(logic, {
                    disabled: true,
                })
        })
        it('disable for `all time` date filter', async () => {
            router.actions.push(urls.insightView('1' as InsightShortId, { date_from: 'all' }))
            await expectLogic(router)
                .toDispatchActions(['push', 'locationChanged'])
                .toDispatchActions([logic.actionCreators.setDisabled(true)])
                .toMatchValues(logic, {
                    disabled: true,
                })
        })
    })
})
