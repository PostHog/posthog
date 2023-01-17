import { kea } from 'kea'
import { objectsEqual, dateMapping } from 'lib/utils'
import type { intervalFilterLogicType } from './intervalFilterLogicType'
import { IntervalKeyType, Intervals, intervals } from 'lib/components/IntervalFilter/intervals'
import { insightLogic } from 'scenes/insights/insightLogic'
import { BaseMathType, InsightLogicProps, IntervalType } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { dayjs } from 'lib/dayjs'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { FunnelsQuery, InsightQueryNode, StickinessQuery, TrendsQuery } from '~/queries/schema'
import { lemonToast } from '../lemonToast'

export const intervalFilterLogic = kea<intervalFilterLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('new'),
    path: (key) => ['lib', 'components', 'IntervalFilter', 'intervalFilterLogic', key],
    connect: (props: InsightLogicProps) => ({
        actions: [insightLogic(props), ['setFilters'], insightDataLogic(props), ['updateQuerySource']],
        values: [insightLogic(props), ['filters'], insightDataLogic(props), ['querySource']],
    }),
    actions: () => ({
        setInterval: (interval: IntervalKeyType) => ({ interval }),
        setEnabledIntervals: (enabledIntervals: Intervals) => ({ enabledIntervals }),
    }),
    reducers: () => ({
        enabledIntervals: [
            { ...intervals },
            {
                setEnabledIntervals: (_, { enabledIntervals }) => enabledIntervals,
            },
        ],
    }),
    listeners: ({ values, actions, selectors }) => ({
        setInterval: ({ interval }) => {
            if (!objectsEqual(interval, values.filters.interval)) {
                actions.setFilters({ ...values.filters, interval })
            }

            if ((values.querySource as FunnelsQuery | StickinessQuery | TrendsQuery).interval !== interval) {
                actions.updateQuerySource({ interval } as Partial<InsightQueryNode>)
            }
        },
        setFilters: ({ filters }, _, __, previousState) => {
            const { date_from, date_to } = filters
            const previousFilters = selectors.filters(previousState)

            let activeUsersMath: BaseMathType.WeeklyActiveUsers | BaseMathType.MonthlyActiveUsers | null = null

            // We disallow grouping by certain intervals for weekly active users and monthly active users views
            // e.g. WAUs grouped by month. Here, look for the first event/action running WAUs/MAUs math and
            // pass that down to the interval filter to determine what groupings are allowed.
            for (const series of [...(values.filters.events || []), ...(values.filters.actions || [])]) {
                if (series.math === BaseMathType.WeeklyActiveUsers) {
                    activeUsersMath = BaseMathType.WeeklyActiveUsers
                    break
                }

                if (series.math === BaseMathType.MonthlyActiveUsers) {
                    activeUsersMath = BaseMathType.MonthlyActiveUsers
                    break
                }
            }

            const enabledIntervals: Intervals = { ...intervals }

            if (activeUsersMath) {
                // Disallow grouping by hour for WAUs/MAUs as it's an expensive query that produces a view that's not useful for users
                enabledIntervals.hour = {
                    label: 'Hour',
                    newDateFrom: 'dStart',
                    disabledReason:
                        'Grouping by hour is not supported on insights with weekly and monthly active users.',
                }

                // Disallow grouping by month for WAUs as the resulting view is misleading to users
                if (activeUsersMath === BaseMathType.WeeklyActiveUsers) {
                    enabledIntervals.month = {
                        label: 'Month',
                        newDateFrom: '-90d',
                        disabledReason: 'Grouping by month is not supported on insights with weekly active users.',
                    }
                }
            }

            actions.setEnabledIntervals(enabledIntervals)

            // If the user just flipped an event action to use WAUs/MAUs math and their
            // current interval is unsupported by the math type, switch their interval
            // to an appropriate allowed interval and inform them of the change via a toast
            if (values.interval && !!enabledIntervals[values.interval].disabledReason) {
                const humanReadableMathType =
                    activeUsersMath === BaseMathType.MonthlyActiveUsers ? 'Monthly active users' : 'Weekly active users'

                if (values.interval === 'hour') {
                    lemonToast.info(
                        `${humanReadableMathType} does not support grouping by hour. Grouping by day instead.`
                    )
                    actions.setInterval('day')
                } else {
                    lemonToast.info(
                        `${humanReadableMathType} does not support grouping by month. Grouping by week instead.`
                    )
                    actions.setInterval('week')
                }
                return
            }

            if (
                !date_from ||
                (objectsEqual(date_from, previousFilters.date_from) && objectsEqual(date_to, previousFilters.date_to))
            ) {
                return
            }

            // automatically set an interval for fixed date ranges
            if (date_from && date_to && dayjs(filters.date_from).isValid() && dayjs(filters.date_to).isValid()) {
                if (dayjs(date_to).diff(dayjs(date_from), 'day') <= 3) {
                    actions.setInterval('hour')
                } else if (dayjs(date_to).diff(dayjs(date_from), 'month') <= 3) {
                    actions.setInterval('day')
                } else {
                    actions.setInterval('month')
                }
                return
            }
            // get a defaultInterval for dateOptions that have a default value
            let interval: IntervalType = 'day'
            for (const { key, values, defaultInterval } of dateMapping) {
                if (
                    values[0] === date_from &&
                    values[1] === (date_to || undefined) &&
                    key !== 'Custom' &&
                    defaultInterval
                ) {
                    interval = defaultInterval
                    break
                }
            }
            actions.setInterval(interval)
        },
    }),
    selectors: {
        interval: [(s) => [s.filters], (filters) => filters?.interval],
    },
})
