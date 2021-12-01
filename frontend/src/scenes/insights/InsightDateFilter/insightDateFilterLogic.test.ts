import { initKeaTestLogic } from '~/test/init'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { insightDateFilterLogic } from 'scenes/insights/InsightDateFilter/insightDateFilterLogic'

const insightsURL = (
    additionalPathPart: string = '',
    dateFrom?: string | undefined,
    dateTo?: string | undefined
): string => {
    let url = `/insights/smosHASp${additionalPathPart}?insight=TRENDS&interval=day&actions=%5B%5D&events=%5B%7B"id"%3A"%24pageview"%2C"name"%3A"%24pageview"%2C"type"%3A"events"%2C"order"%3A0%7D%5D&properties=%5B%5D&filter_test_accounts=false&display=ActionsPie`
    if (dateFrom) {
        url = `${url}&date_from=${dateFrom}`
    }
    if (dateTo) {
        url = `${url}&date_to=${dateTo}`
    }
    return url
}

describe('the insightDateFilterLogic', () => {
    let logic: ReturnType<typeof insightDateFilterLogic.build>

    initKeaTestLogic({
        logic: insightDateFilterLogic,
        props: {},
        onLogic: (l) => (logic = l),
    })

    it('defaults to no dates', () => {
        expectLogic(logic).toMatchValues({ dates: { dateFrom: undefined, dateTo: undefined } })
    })

    it('reads "date from" and "date to" from URL when editing', () => {
        expectLogic(logic, () => {
            router.actions.push(insightsURL('', '2021-12-13', '2022-01-14'))
        }).toMatchValues({ dates: { dateFrom: '2021-12-13', dateTo: '2022-01-14' } })
    })

    it('reads "date from" and "date to" from URL when viewing', () => {
        expectLogic(logic, () => {
            router.actions.push(insightsURL('/edit', '2021-12-14', '2022-01-15'))
        }).toMatchValues({ dates: { dateFrom: '2021-12-14', dateTo: '2022-01-15' } })
    })
})
