import { initKeaTests } from '~/test/init'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { insightDateFilterLogic } from 'scenes/insights/InsightDateFilter/insightDateFilterLogic'
import { urls } from 'scenes/urls'
import { InsightLogicProps, InsightShortId } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'

describe('the insightDateFilterLogic', () => {
    let logic: ReturnType<typeof insightDateFilterLogic.build>

    beforeEach(() => {
        const insightProps: InsightLogicProps = { dashboardItemId: '12345' as InsightShortId, syncWithUrl: true }
        initKeaTests()
        insightLogic(insightProps).mount()
        logic = insightDateFilterLogic(insightProps)
        logic.mount()
    })

    it('defaults to no dates', () => {
        expectLogic(logic).toMatchValues({ dates: { dateFrom: null, dateTo: null } })
    })

    it('reads "date from" and "date to" from URL when editing', () => {
        const url = urls.insightEdit('12345' as InsightShortId, {
            date_from: '2021-12-13',
            date_to: '2021-12-14',
        })
        expectLogic(logic, () => {
            router.actions.push(url)
        }).toMatchValues({ dates: { dateFrom: '2021-12-13', dateTo: '2021-12-14' } })
    })

    it('reads "date from" and "date to" from URL when viewing', () => {
        const url = urls.insightView('12345' as InsightShortId, {
            date_from: '2021-12-14',
            date_to: '2021-12-15',
        })
        expectLogic(logic, () => {
            router.actions.push(url)
        }).toMatchValues({ dates: { dateFrom: '2021-12-14', dateTo: '2021-12-15' } })
    })
})
