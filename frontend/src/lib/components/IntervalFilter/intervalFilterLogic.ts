import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { IntervalKeyType, Intervals, intervals } from 'lib/components/IntervalFilter/intervals'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { dateMapping, objectsEqual } from 'lib/utils'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { BASE_MATH_DEFINITIONS } from 'scenes/trends/mathsLogic'

import { InsightQueryNode, TrendsQuery } from '~/queries/schema'
import { BaseMathType, InsightLogicProps, IntervalType } from '~/types'

import type { intervalFilterLogicType } from './intervalFilterLogicType'

export const intervalFilterLogic = kea<intervalFilterLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['lib', 'components', 'IntervalFilter', 'intervalFilterLogic', key]),
    connect((props: InsightLogicProps) => ({
        actions: [insightVizDataLogic(props), ['updateQuerySource']],
        values: [insightVizDataLogic(props), ['interval', 'querySource']],
    })),
    actions(() => ({
        setInterval: (interval: IntervalKeyType) => ({ interval }),
        setEnabledIntervals: (enabledIntervals: Intervals) => ({ enabledIntervals }),
    })),
    reducers(() => ({
        enabledIntervals: [
            { ...intervals } as Intervals,
            {
                setEnabledIntervals: (_, { enabledIntervals }) => enabledIntervals,
            },
        ],
    })),
    listeners(({ values, actions, selectors }) => ({
        setInterval: ({ interval }) => {
            if (values.interval !== interval) {
                actions.updateQuerySource({ interval } as Partial<InsightQueryNode>)
            }
        },
        updateQuerySource: ({ querySource }, _, __, previousState) => {
            const { date_from, date_to } = querySource.dateRange || {}
            const previousDateRange = selectors.querySource(previousState)?.dateRange || {}

            let activeUsersMath: BaseMathType.WeeklyActiveUsers | BaseMathType.MonthlyActiveUsers | null = null

            // We disallow grouping by certain intervals for weekly active users and monthly active users views
            // e.g. WAUs grouped by month. Here, look for the first event/action running WAUs/MAUs math and
            // pass that down to the interval filter to determine what groupings are allowed.
            for (const series of (values.querySource as TrendsQuery)?.series || []) {
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
                    ...enabledIntervals.hour,
                    disabledReason:
                        'Grouping by hour is not supported on insights with weekly or monthly active users series.',
                }

                // Disallow grouping by month for WAUs as the resulting view is misleading to users
                if (activeUsersMath === BaseMathType.WeeklyActiveUsers) {
                    enabledIntervals.month = {
                        ...enabledIntervals.month,
                        disabledReason:
                            'Grouping by month is not supported on insights with weekly active users series.',
                    }
                }
            }

            actions.setEnabledIntervals(enabledIntervals)

            // If the user just flipped an event action to use WAUs/MAUs math and their
            // current interval is unsupported by the math type, switch their interval
            // to an appropriate allowed interval and inform them of the change via a toast
            if (
                activeUsersMath &&
                (values.querySource as TrendsQuery)?.interval &&
                enabledIntervals[(values.querySource as TrendsQuery).interval as IntervalType].disabledReason
            ) {
                if (values.interval === 'hour') {
                    lemonToast.info(
                        `Switched to grouping by day, because "${BASE_MATH_DEFINITIONS[activeUsersMath].name}" does not support grouping by ${values.interval}.`
                    )
                    actions.updateQuerySource({ interval: 'day' } as Partial<InsightQueryNode>)
                } else {
                    lemonToast.info(
                        `Switched to grouping by week, because "${BASE_MATH_DEFINITIONS[activeUsersMath].name}" does not support grouping by ${values.interval}.`
                    )
                    actions.updateQuerySource({ interval: 'week' } as Partial<InsightQueryNode>)
                }
                return
            }

            if (
                !date_from ||
                (objectsEqual(date_from, previousDateRange.date_from) &&
                    objectsEqual(date_to, previousDateRange.date_to))
            ) {
                return
            }

            // automatically set an interval for fixed date ranges
            if (
                date_from &&
                date_to &&
                dayjs(querySource.dateRange?.date_from).isValid() &&
                dayjs(querySource.dateRange?.date_to).isValid()
            ) {
                if (dayjs(date_to).diff(dayjs(date_from), 'day') <= 3) {
                    actions.updateQuerySource({ interval: 'hour' } as Partial<InsightQueryNode>)
                } else if (dayjs(date_to).diff(dayjs(date_from), 'month') <= 3) {
                    actions.updateQuerySource({ interval: 'day' } as Partial<InsightQueryNode>)
                } else {
                    actions.updateQuerySource({ interval: 'month' } as Partial<InsightQueryNode>)
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
            actions.updateQuerySource({ interval } as Partial<InsightQueryNode>)
        },
    })),
])
