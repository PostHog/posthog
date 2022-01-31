import { chartFilterLogic } from 'lib/components/ChartFilter/chartFilterLogic'
import { initKeaTests } from '~/test/init'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { urls } from 'scenes/urls'
import { ChartDisplayType, InsightLogicProps, InsightShortId } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'

describe('the chart filter', () => {
    let logic: ReturnType<typeof chartFilterLogic.build>

    beforeEach(() => {
        initKeaTests()
        const logicProps: InsightLogicProps = { dashboardItemId: '1' as InsightShortId, syncWithUrl: true }
        insightLogic(logicProps).mount()
        logic = chartFilterLogic(logicProps)
        logic.mount()
    })

    it('defaults to null', () => {
        expectLogic(logic).toMatchValues({ chartFilter: null })
    })

    it('reads display type from URL when editing', () => {
        const url = urls.insightEdit('12345' as InsightShortId, {
            display: ChartDisplayType.ActionsPieChart,
        })
        expectLogic(logic, () => {
            router.actions.push(url)
        }).toMatchValues({ chartFilter: 'ActionsPie' })
    })

    it('reads display type from URL when viewing', () => {
        const url = urls.insightView('12345' as InsightShortId, {
            display: ChartDisplayType.ActionsPieChart,
        })
        expectLogic(logic, () => {
            router.actions.push(url)
        }).toMatchValues({ chartFilter: 'ActionsPie' })
    })
})
