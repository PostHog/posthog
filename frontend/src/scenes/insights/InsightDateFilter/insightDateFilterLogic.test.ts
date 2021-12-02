import { initKeaTestLogic } from '~/test/init'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { insightDateFilterLogic } from 'scenes/insights/InsightDateFilter/insightDateFilterLogic'
import { urls } from 'scenes/urls'
import { InsightShortId } from '~/types'

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
