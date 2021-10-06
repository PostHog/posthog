import { kea } from 'kea'
import { Dayjs } from 'dayjs'
import { objectsEqual } from 'lib/utils'
import { insightDateFilterLogicType } from './insightDateFilterLogicType'
import { insightLogic } from 'scenes/insights/insightLogic'

interface InsightDateFilterLogicProps {
    dashboardItemId?: number
}

export const insightDateFilterLogic = kea<insightDateFilterLogicType<InsightDateFilterLogicProps>>({
    props: {} as InsightDateFilterLogicProps,
    key: (props) => props.dashboardItemId || 'new',
    connect: (props: InsightDateFilterLogicProps) => ({
        values: [insightLogic({ id: props.dashboardItemId }), ['filters']],
        actions: [insightLogic({ id: props.dashboardItemId }), ['updateInsightFilters']],
    }),
    actions: () => ({
        setDates: (dateFrom: string | Dayjs | undefined, dateTo: string | Dayjs | undefined) => ({
            dateFrom,
            dateTo,
        }),
        dateAutomaticallyChanged: true,
        endHighlightChange: true,
        setInitialLoad: true,
    }),
    selectors: {
        dates: [
            (s) => [s.filters],
            (filters) => ({
                dateFrom: filters.date_from,
                dateTo: filters.date_to,
            }),
        ],
    },
    reducers: () => ({
        highlightDateChange: [
            false,
            {
                dateAutomaticallyChanged: () => true,
                endHighlightChange: () => false,
            },
        ],
        initialLoad: [
            true,
            {
                setInitialLoad: () => false,
            },
        ],
    }),
    listeners: ({ values, actions }) => ({
        setDates: ({ dateFrom, dateTo }) => {
            if (!objectsEqual(dateFrom, values.filters.date_from) || !objectsEqual(dateTo, values.filters.date_to)) {
                actions.updateInsightFilters({
                    ...values.filters,
                    date_from: dateFrom?.toString(),
                    date_to: dateTo?.toString(),
                })
            }
        },
        dateAutomaticallyChanged: async (_, breakpoint) => {
            await breakpoint(2000)
            actions.endHighlightChange()
        },
    }),
})
