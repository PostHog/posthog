import { BindLogic, useActions, useValues } from 'kea'

import { IconPlusSmall, IconRefresh, IconX } from '@posthog/icons'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { UsageMetricsConfig, UsageMetricsModal } from 'scenes/settings/environment/UsageMetricsConfig'
import { usageMetricsConfigLogic } from 'scenes/settings/environment/usageMetricsConfigLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { NodeKind, ProductKey, UsageMetric, UsageMetricsQueryResponse } from '~/queries/schema/schema-general'

import {
    UsageMetricCard,
    UsageMetricCardSkeleton,
} from 'products/customer_analytics/frontend/components/UsageMetricCard'
import { customerProfileLogic } from 'products/customer_analytics/frontend/customerProfileLogic'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { createPostHogWidgetNode } from './NodeWrapper'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeUsageMetricsAttributes>): JSX.Element | null => {
    const { expanded } = useValues(notebookNodeLogic)
    const { setActions, setMenuItems } = useActions(notebookNodeLogic)
    const { personId, groupKey, groupTypeIndex, tabId } = attributes
    const dataNodeLogicProps = personId
        ? {
              query: {
                  kind: NodeKind.UsageMetricsQuery,
                  person_id: personId,
              },
              key: `${personId}-${tabId}`,
          }
        : groupKey
          ? {
                query: {
                    kind: NodeKind.UsageMetricsQuery,
                    group_key: groupKey,
                    group_type_index: groupTypeIndex,
                },
                key: `${groupKey}-${tabId}`,
            }
          : { key: 'error', query: { kind: NodeKind.UsageMetricsQuery } }
    const logic = dataNodeLogic(dataNodeLogicProps)
    const { response, responseLoading, responseError } = useValues(logic)
    const { loadData } = useActions(logic)
    const usageMetricsConfigLogicProps = { logicKey: attributes.nodeId }
    const { openModal } = useActions(usageMetricsConfigLogic(usageMetricsConfigLogicProps))
    const { removeNode } = useActions(customerProfileLogic)

    useOnMountEffect(() => {
        setActions([
            {
                text: 'Add metric',
                icon: <IconPlusSmall />,
                onClick: openModal,
            },
            {
                text: 'Refresh',
                icon: <IconRefresh />,
                onClick: loadData,
            },
        ])

        setMenuItems([
            {
                label: 'Add metric',
                sideIcon: <IconPlusSmall />,
                onClick: openModal,
            },
            {
                label: 'Refresh',
                sideIcon: <IconRefresh />,
                onClick: () => loadData(),
            },
            {
                label: 'Remove',
                onClick: () => removeNode(NotebookNodeType.UsageMetrics),
                sideIcon: <IconX />,
                status: 'danger',
            },
        ])
    })

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
        return (
            <BindLogic logic={usageMetricsConfigLogic} props={usageMetricsConfigLogicProps}>
                <UsageMetricsEmptyState />
                <UsageMetricsModal />
            </BindLogic>
        )
    }

    return (
        <BindLogic logic={usageMetricsConfigLogic} props={usageMetricsConfigLogicProps}>
            <div className="@container">
                <div className="grid grid-cols-1 @md:grid-cols-2 @xl:grid-cols-4 gap-4 p-4">
                    {results.map((metric) => (
                        <UsageMetricCard key={metric.id} metric={metric} />
                    ))}
                </div>
                <UsageMetricsModal />
            </div>
        </BindLogic>
    )
}

function UsageMetricsEmptyState(): JSX.Element {
    const { openModal } = useActions(usageMetricsConfigLogic)
    return (
        <ProductIntroduction
            productName="Customer analytics"
            thingName="usage metric"
            description="Once created, usage metrics will be displayed here."
            isEmpty={true}
            productKey={ProductKey.CUSTOMER_ANALYTICS}
            className="border-none"
            action={() => openModal()}
        />
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
    tabId: string
}

export const NotebookNodeUsageMetrics = createPostHogWidgetNode<NotebookNodeUsageMetricsAttributes>({
    nodeType: NotebookNodeType.UsageMetrics,
    titlePlaceholder: 'Usage',
    Component,
    Settings,
    resizeable: false,
    expandable: true,
    startExpanded: true,
    attributes: {
        personId: {},
        groupKey: {},
        groupTypeIndex: {},
        tabId: {},
    },
})
