import { chartFilterLogic } from 'lib/components/ChartFilter/chartFilterLogic'
import { initKeaTestLogic } from '~/test/init'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { urls } from 'scenes/urls'
import { ChartDisplayType, InsightShortId } from '~/types'

describe('the chart filter', () => {
    let logic: ReturnType<typeof chartFilterLogic.build>

    initKeaTestLogic({
        logic: chartFilterLogic,
        props: {},
        onLogic: (l) => (logic = l),
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
