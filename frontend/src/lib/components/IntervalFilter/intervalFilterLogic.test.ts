import { initKeaTestLogic } from '~/test/init'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { intervalFilterLogic } from 'lib/components/IntervalFilter/intervalFilterLogic'
import { urls } from 'scenes/urls'
import { InsightShortId } from '~/types'

describe('intervalFilterLogic', () => {
    let logic: ReturnType<typeof intervalFilterLogic.build>

    initKeaTestLogic({
        logic: intervalFilterLogic,
        props: {},
        onLogic: (l) => (logic = l),
    })

    it('defaults to null', () => {
        expectLogic(logic).toMatchValues({ interval: null })
    })

    it('reads "interval" from URL when editing', () => {
        const url = urls.insightEdit('12345' as InsightShortId, {
            interval: 'hour',
        })
        expectLogic(logic, () => {
            router.actions.push(url)
        }).toMatchValues({ interval: 'hour' })
    })

    it('reads "interval" from URL when viewing', () => {
        const url = urls.insightView('12345' as InsightShortId, {
            interval: 'week',
        })
        expectLogic(logic, () => {
            router.actions.push(url)
        }).toMatchValues({ interval: 'week' })
    })
})
