import { kea } from 'kea'
import type { intervalFilterLogicType } from './intervalFilterLogicType'
import { IntervalKeyType, Intervals, intervals } from 'lib/components/IntervalFilter/intervals'
import { BaseMathType, InsightLogicProps } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { InsightQueryNode } from '~/queries/schema'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export const intervalFilterLogic = kea<intervalFilterLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('new'),
    path: (key) => ['lib', 'components', 'IntervalFilter', 'intervalFilterLogic', key],
    connect: (props: InsightLogicProps) => ({
        actions: [insightVizDataLogic(props), ['updateQuerySource']],
        values: [insightVizDataLogic(props), ['interval', 'querySource', 'activeUsersMath']],
    }),
    actions: () => ({
        setInterval: (interval: IntervalKeyType) => ({ interval }),
    }),
    selectors: () => ({
        enabledIntervals: [
            (s) => [s.activeUsersMath],
            (activeUsersMath) => {
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

                return enabledIntervals
            },
        ],
    }),
    listeners: ({ values, actions }) => ({
        setInterval: ({ interval }) => {
            if (values.interval !== interval) {
                actions.updateQuerySource({ interval } as Partial<InsightQueryNode>)
            }
        },
    }),
})
