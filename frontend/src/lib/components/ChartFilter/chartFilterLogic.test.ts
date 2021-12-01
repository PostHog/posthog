import { chartFilterLogic } from 'lib/components/ChartFilter/chartFilterLogic'
import { initKeaTestLogic } from '~/test/init'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

const insightsURL = (additionalPathPart: string = ''): string =>
    `/insights/smosHASp${additionalPathPart}?insight=TRENDS&interval=day&actions=%5B%5D&events=%5B%7B"id"%3A"%24pageview"%2C"name"%3A"%24pageview"%2C"type"%3A"events"%2C"order"%3A0%7D%5D&properties=%5B%5D&filter_test_accounts=false&display=ActionsPie`

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
        expectLogic(logic, () => {
            router.actions.push(insightsURL())
        }).toMatchValues({ chartFilter: 'ActionsPie' })
    })

    it('reads display type from URL when viewing', () => {
        expectLogic(logic, () => {
            router.actions.push(insightsURL('/edit'))
        }).toMatchValues({ chartFilter: 'ActionsPie' })
    })
})
