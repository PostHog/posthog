import { initKeaTestLogic } from '~/test/init'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { smoothingFilterLogic } from 'lib/components/SmoothingFilter/smoothingFilterLogic'
import { urls } from 'scenes/urls'
import { InsightShortId, InsightType } from '~/types'

describe('the smoothingFilterLogic', () => {
    let logic: ReturnType<typeof smoothingFilterLogic.build>

    initKeaTestLogic({
        logic: smoothingFilterLogic,
        props: {
            dashboardItemId: undefined,
            syncWithUrl: true,
            filters: {
                insight: InsightType.TRENDS,
            },
        },
        onLogic: (l) => (logic = l),
    })

    it('sets a default for smoothing interval', () => {
        const url = urls.insightEdit('12345' as InsightShortId, {})

        expectLogic(logic, () => {
            router.actions.push(url)
        }).toMatchValues({ filters: expect.objectContaining({ smoothing_intervals: 1 }) })
    })

    it('reads "smoothing_intervals" from URL when editing', () => {
        const url = urls.insightEdit('12345' as InsightShortId, {
            smoothing_intervals: 7,
            interval: 'day',
        })

        expectLogic(logic, () => {
            router.actions.push(url)
        }).toMatchValues({ filters: expect.objectContaining({ smoothing_intervals: 7, interval: 'day' }) })
    })

    it('reads "smoothing_intervals" from URL when viewing', () => {
        const url = urls.insightView('12345' as InsightShortId, {
            smoothing_intervals: 7,
            interval: 'day',
        })

        expectLogic(logic, () => {
            router.actions.push(url)
        }).toMatchValues({ filters: expect.objectContaining({ smoothing_intervals: 7, interval: 'day' }) })
    })

    it('reads "smoothing_intervals" and "interval" from URL when viewing and corrects bad pairings', () => {
        const url = urls.insightView('12345' as InsightShortId, {
            // you can't have 4 day smoothing with day interval
            smoothing_intervals: 4,
            interval: 'day',
        })

        expectLogic(logic, () => {
            router.actions.push(url)
        }).toMatchValues({ filters: expect.objectContaining({ smoothing_intervals: 1, interval: 'day' }) })
    })
})
