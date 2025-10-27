import { BindLogic, useValues } from 'kea'

import { UsageMetricsConfig } from 'scenes/settings/environment/UsageMetricsConfig'
import { usageMetricsConfigLogic } from 'scenes/settings/environment/usageMetricsConfigLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { NodeKind, UsageMetric, UsageMetricsQueryResponse } from '~/queries/schema/schema-general'

import {
    UsageMetricCard,
    UsageMetricCardSkeleton,
} from 'products/customer_analytics/frontend/components/UsageMetricCard'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { createPostHogWidgetNode } from './NodeWrapper'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeUsageMetricsAttributes>): JSX.Element | null => {
    const { expanded } = useValues(notebookNodeLogic)
    const { personId, groupKey, groupTypeIndex } = attributes
    const dataNodeLogicProps = personId
        ? {
              query: {
                  kind: NodeKind.UsageMetricsQuery,
                  person_id: personId,
              },
              key: personId,
          }
        : groupKey
          ? {
                query: {
                    kind: NodeKind.UsageMetricsQuery,
                    group_key: groupKey,
                    group_type_index: groupTypeIndex,
                },
                key: groupKey,
            }
          : { key: 'error', query: { kind: NodeKind.UsageMetricsQuery } }
    const logic = dataNodeLogic(dataNodeLogicProps)
    const { response, responseLoading, responseError } = useValues(logic)

    if (!expanded) {
        return null
    }

    if (responseLoading) {
        return <UsageMetricCardSkeleton />
    }

    if (responseError) {
        return <div className="text-danger text-center p-4">Failed to load usage metrics</div>
    }

    const queryResponse = response as UsageMetricsQueryResponse | undefined
    const results = (queryResponse?.results ?? []) as UsageMetric[]
    const hasResults = results.length > 0

    if (!hasResults) {
        return <div className="text-muted text-center p-4">No usage metrics available</div>
    }

    return (
        <div className="@container">
            <div className="grid grid-cols-1 @md:grid-cols-2 @xl:grid-cols-4 gap-4 p-4">
                {results.map((metric) => (
                    <UsageMetricCard key={metric.id} metric={metric} />
                ))}
            </div>
        </div>
    )
}

const Settings = ({ attributes }: NotebookNodeAttributeProperties<NotebookNodeUsageMetricsAttributes>): JSX.Element => {
    return (
        <div className="p-2">
            <BindLogic logic={usageMetricsConfigLogic} props={{ logicKey: attributes.nodeId }}>
                <UsageMetricsConfig />
            </BindLogic>
        </div>
    )
}

type NotebookNodeUsageMetricsAttributes = {
    personId?: string
    groupKey?: string
    groupTypeIndex?: number
}

export const NotebookNodeUsageMetrics = createPostHogWidgetNode<NotebookNodeUsageMetricsAttributes>({
    nodeType: NotebookNodeType.UsageMetrics,
    titlePlaceholder: 'Usage',
    Component,
    Settings,
    settingsIcon: 'gear',
    resizeable: false,
    expandable: true,
    startExpanded: true,
    attributes: {
        personId: {},
        groupKey: {},
        groupTypeIndex: {},
    },
})
