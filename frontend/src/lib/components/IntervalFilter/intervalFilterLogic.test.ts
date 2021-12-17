import { initKeaTestLogic } from '~/test/init'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { intervalFilterLogic } from 'lib/components/IntervalFilter/intervalFilterLogic'
import { urls } from 'scenes/urls'
import { InsightShortId, InsightType } from '~/types'

describe('the intervalFilterLogic', () => {
    let logic: ReturnType<typeof intervalFilterLogic.build>

    initKeaTestLogic({
        logic: intervalFilterLogic,
        props: {
            dashboardItemId: undefined,
            syncWithUrl: true,
            filters: {
                insight: InsightType.TRENDS,
            },
        },
        onLogic: (l) => (logic = l),
    })

    it('sets a default for interval, and excludes date_from', () => {
        const url = urls.insightEdit('12345' as InsightShortId, {})

        expectLogic(logic, () => {
            router.actions.push(url)
        }).toMatchValues({ filters: expect.objectContaining({ interval: 'day' }) })
    })

    it('reads "date from" and "interval" from URL when editing', () => {
        const url = urls.insightEdit('12345' as InsightShortId, {
            date_from: '-30d',
            interval: 'hour',
        })
        expectLogic(logic, () => {
            router.actions.push(url)
        }).toMatchValues({ filters: expect.objectContaining({ date_from: '-30d', interval: 'hour' }) })
    })

    it('reads "date from" and "interval" from URL when viewing', () => {
        const url = urls.insightView('12345' as InsightShortId, {
            date_from: '-14d',
            interval: 'week',
        })

        expectLogic(logic, () => {
            router.actions.push(url)
        }).toMatchValues({ filters: expect.objectContaining({ date_from: '-14d', interval: 'week' }) })
    })
})
