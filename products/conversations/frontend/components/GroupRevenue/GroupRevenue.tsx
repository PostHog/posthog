import { useValues } from 'kea'

import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { formatCurrency } from 'lib/utils/currency'
import { DataSourceIcon } from 'scenes/notebooks/Nodes/components/DataSourceIcon'
import { teamLogic } from 'scenes/teamLogic'

import type { GroupRevenue as GroupRevenueData } from '../../scenes/ticket/groupRevenue'

export interface GroupRevenueProps {
    revenue: GroupRevenueData
    loading?: boolean
}

export function GroupRevenue({ revenue, loading = false }: GroupRevenueProps): JSX.Element | null {
    const { baseCurrency } = useValues(teamLogic)

    if (loading) {
        return <LemonSkeleton className="h-3 w-40" />
    }

    const { mrr, lifetimeValue } = revenue
    if (mrr.value === null && lifetimeValue.value === null) {
        return null
    }

    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs" data-attr="ticket-group-revenue">
            {mrr.value !== null && (
                <div className="flex items-center gap-1">
                    <Tooltip title="Monthly recurring revenue">
                        <span className="text-secondary">MRR</span>
                    </Tooltip>
                    <span translate="no">{formatCurrency(mrr.value, baseCurrency)}</span>
                    <DataSourceIcon source={mrr.source} />
                </div>
            )}
            {lifetimeValue.value !== null && (
                <div className="flex items-center gap-1">
                    <Tooltip title="Total revenue from this customer over the whole relationship">
                        <span className="text-secondary">Lifetime value</span>
                    </Tooltip>
                    <span translate="no">{formatCurrency(lifetimeValue.value, baseCurrency)}</span>
                    <DataSourceIcon source={lifetimeValue.source} />
                </div>
            )}
        </div>
    )
}
