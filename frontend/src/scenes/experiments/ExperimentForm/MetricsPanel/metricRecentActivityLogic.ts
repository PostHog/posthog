import equal from 'fast-deep-equal'
import { afterMount, kea, key, path, props, propsChanged } from 'kea'
import { loaders } from 'kea-loaders'

import { performQuery } from '~/queries/query'
import type { ExperimentMetric } from '~/queries/schema/schema-general'
import { getEventCountQuery } from '~/scenes/experiments/utils'

import type { metricRecentActivityLogicType } from './metricRecentActivityLogicType'

export type MetricRecentActivityLogicProps = {
    metric: ExperimentMetric
    filterTestAccounts: boolean
}

export const metricRecentActivityLogic = kea<metricRecentActivityLogicType>([
    props({} as MetricRecentActivityLogicProps),
    key((props) => `${props.metric.uuid}`),
    path((key) => ['scenes', 'experiments', 'create', 'metricRecentActivityLogic', key]),
    loaders(({ props }) => ({
        eventCount: [
            null as number | null,
            {
                loadEventCount: async () => {
                    const query = getEventCountQuery(props.metric, props.filterTestAccounts)

                    if (!query) {
                        return null
                    }

                    const response = await performQuery(query)

                    if (response.results && response.results.length > 0) {
                        const firstResult = response.results[0]
                        if (firstResult && typeof firstResult.aggregated_value === 'number') {
                            return firstResult.aggregated_value
                        }
                    }

                    return null
                },
            },
        ],
    })),
    afterMount(({ actions, props }) => {
        if (props.metric.uuid) {
            actions.loadEventCount()
        }
    }),
    propsChanged(({ actions, props }, oldProps) => {
        /**
         * this brings back memories of componentWillReceiveProps...
         */
        if (!equal(props, oldProps)) {
            actions.loadEventCount()
        }
    }),
])
