import { kea } from 'kea'
import { objectsEqual, dateMappingExperiment as dateMapping } from 'lib/utils'
import type { intervalFilterLogicType } from './intervalFilterLogicType'
import { IntervalKeyType } from 'lib/components/IntervalFilter/intervals'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightLogicProps, IntervalType } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export const intervalFilterLogic = kea<intervalFilterLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('new'),
    path: (key) => ['lib', 'components', 'IntervalFilter', 'intervalFilterLogic', key],
    connect: (props: InsightLogicProps) => ({
        actions: [insightLogic(props), ['setFilters']],
        values: [insightLogic(props), ['filters'], featureFlagLogic, ['featureFlags']],
    }),
    actions: () => ({
        setInterval: (interval: IntervalKeyType) => ({ interval }),
    }),
    listeners: ({ values, actions, selectors }) => ({
        setInterval: ({ interval }) => {
            if (!objectsEqual(interval, values.filters.interval)) {
                actions.setFilters({ ...values.filters, interval })
            }
        },
        setFilters: ({ filters }, _, __, previousState) => {
            if (values.featureFlags[FEATURE_FLAGS.DATE_FILTER_EXPERIMENT] === 'control') {
                return
            }

            const { date_from, date_to } = filters
            const previousFilters = selectors.filters(previousState)
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
            Object.entries(dateMapping).map(([key, { values, defaultInterval }]) => {
                if (values[0] === date_from && values[1] === (date_to || undefined) && key !== 'Custom') {
                    if (defaultInterval) {
                        interval = defaultInterval
                    }
                }
            })[0]
            actions.setInterval(interval)
        },
    }),
    selectors: {
        interval: [(s) => [s.filters], (filters) => filters?.interval],
    },
})
