import { afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import type { linkMetricSparklineLogicType } from './linkMetricSparklineLogicType'

export type Props = {
    id: string
}

export const linkMetricSparklineLogic = kea<linkMetricSparklineLogicType>([
    props({} as Props),
    key(({ id }: Props) => id),
    path((id) => ['scenes', 'links', 'linkMetricSparklineLogic', id]),
    loaders(() => ({
        sparklineData: [
            null,
            {
                loadSparklineData: async () => {
                    const query: TrendsQuery = {
                        kind: NodeKind.TrendsQuery,
                        filterTestAccounts: false,
                        trendsFilter: {
                            display: ChartDisplayType.ActionsBar,
                        },
                        series: [
                            {
                                kind: NodeKind.EventsNode,
                                event: '$pageview',
                                name: '$pageview',
                                // properties: [
                                //     {
                                //         key: '$current_url',
                                //         value: ['http://localhost:8000/project/1/feature_flags/136'],
                                //         operator: PropertyOperator.Exact,
                                //         type: PropertyFilterType.Event,
                                //     },
                                // ],
                            },
                        ],
                    }
                    return await api.query(query)
                },
            },
        ],
    })),
    afterMount(({ actions, props }) => {
        actions.loadSparklineData({ id: props.id })
    }),
])
