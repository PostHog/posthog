import { initKeaTestLogic } from '~/test/init'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { intervalFilterLogic } from 'lib/components/IntervalFilter/intervalFilterLogic'
import { urls } from 'scenes/urls'
import { InsightShortId } from '~/types'

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
        const url = urls.insightEdit('12345' as InsightShortId, {
            date_from: '-90d',
            interval: 'hour',
        })
        expectLogic(logic, () => {
            router.actions.push(url)
        }).toMatchValues({ dateFrom: '-90d', interval: 'hour' })
    })

    it('reads "date from" and "interval" from URL when viewing', () => {
        const url = urls.insightView('12345' as InsightShortId, {
            date_from: '-14d',
            interval: 'week',
        })
        expectLogic(logic, () => {
            router.actions.push(url)
        }).toMatchValues({ dateFrom: '-14d', interval: 'week' })
    })
})
