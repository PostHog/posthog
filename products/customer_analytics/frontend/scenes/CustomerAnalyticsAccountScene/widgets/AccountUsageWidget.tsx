import { useActions, useValues } from 'kea'

import { IconTrending } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { NodeKind, UsageMetric, UsageMetricsQueryResponse } from '~/queries/schema/schema-general'

import {
    UsageMetricCard,
    UsageMetricCardSkeleton,
} from 'products/customer_analytics/frontend/components/UsageMetricCard'
import { CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS } from 'products/customer_analytics/frontend/constants'

import { AccountWidgetHeader } from './AccountWidgetHeader'

interface AccountUsageWidgetProps {
    accountId: string
    externalId: string | null
    groupTypeIndex: number | null
    onRemove?: () => void
}

function UsageState({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="text-sm text-secondary px-1 py-2">{children}</div>
}

function AccountUsageMetrics({
    accountId,
    externalId,
    groupTypeIndex,
}: Omit<AccountUsageWidgetProps, 'onRemove'> & { externalId: string; groupTypeIndex: number }): JSX.Element {
    const logic = dataNodeLogic({
        query: {
            kind: NodeKind.UsageMetricsQuery,
            tags: CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS,
            group_key: externalId,
            group_type_index: groupTypeIndex,
        },
        key: `account-detail-usage-${accountId}`,
    })
    const { response, responseLoading, responseError } = useValues(logic)
    const { loadData } = useActions(logic)
    const results = ((response as UsageMetricsQueryResponse | null)?.results ?? []) as UsageMetric[]

    if (responseLoading && !response) {
        return <UsageMetricCardSkeleton />
    }
    if (responseError) {
        return (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadData() }}>
                Couldn't load usage metrics. Try again.
            </LemonBanner>
        )
    }
    if (results.length === 0) {
        return (
            <UsageState>
                No usage metrics are configured for accounts yet. Add them in the customer analytics settings.
            </UsageState>
        )
    }
    return (
        <div className="grid grid-cols-1 @lg:grid-cols-3 gap-3">
            {results.map((metric) => (
                <UsageMetricCard key={metric.id} metric={metric} />
            ))}
        </div>
    )
}

export function AccountUsageWidget({
    accountId,
    externalId,
    groupTypeIndex,
    onRemove,
}: AccountUsageWidgetProps): JSX.Element {
    return (
        <div className="@2xl:col-span-2 flex flex-col gap-2 min-w-0 @container" data-attr="account-usage-widget">
            <AccountWidgetHeader
                icon={<IconTrending />}
                title="Usage metrics"
                onRemove={onRemove}
                className="flex items-center gap-2 px-1"
            />
            {!externalId ? (
                <UsageState>This account has no external ID, so it cannot be matched to usage data.</UsageState>
            ) : groupTypeIndex === null ? (
                <UsageState>
                    Pick the group type that represents accounts in the customer analytics settings first.
                </UsageState>
            ) : (
                <AccountUsageMetrics accountId={accountId} externalId={externalId} groupTypeIndex={groupTypeIndex} />
            )}
        </div>
    )
}
