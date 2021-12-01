import { initKeaTestLogic } from '~/test/init'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { intervalFilterLogic } from 'lib/components/IntervalFilter/intervalFilterLogic'
import { IntervalKeyType } from 'lib/components/IntervalFilter/intervals'

const insightsURL = (
    additionalPathPart: string = '',
    dateFrom?: '-90d' | '-14d' | undefined,
    interval?: IntervalKeyType | undefined
): string => {
    let url = `/insights/smosHASp${additionalPathPart}?insight=TRENDS&interval=day&actions=%5B%5D&events=%5B%7B"id"%3A"%24pageview"%2C"name"%3A"%24pageview"%2C"type"%3A"events"%2C"order"%3A0%7D%5D&properties=%5B%5D&filter_test_accounts=false&display=ActionsPie`
    if (dateFrom) {
        url = `${url}&date_from=${dateFrom}`
    }
    if (interval) {
        url = `${url}&interval=${interval}`
    }
    return url
}

describe('the intervalFilterLogic', () => {
    let logic: ReturnType<typeof intervalFilterLogic.build>

    initKeaTestLogic({
        logic: intervalFilterLogic,
        props: {},
        onLogic: (l) => (logic = l),
    })

    it('defaults to null', () => {
        expectLogic(logic).toMatchValues({ dateFrom: null, interval: null })
    })

    it('reads "date from" and "interval" from URL when editing', () => {
        expectLogic(logic, () => {
            router.actions.push(insightsURL('', '-90d', 'hour'))
        }).toMatchValues({ dateFrom: '-90d', interval: 'hour' })
    })

    it('reads "date from" and "interval" from URL when viewing', () => {
        expectLogic(logic, () => {
            router.actions.push(insightsURL('/edit', '-14d', 'week'))
        }).toMatchValues({ dateFrom: '-14d', interval: 'week' })
    })
})
