import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSkeleton, LemonTable } from '@posthog/lemon-ui'

import { humanFriendlyCurrency } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { AGENT_SPEND_WINDOW_DAYS, agentUsageLogic } from './agentUsageLogic'

function SpendStat({ label, value }: { label: string; value: number }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 min-w-32 flex-1">
            <span className="text-secondary text-xs">{label}</span>
            <span className="text-xl font-semibold" translate="no">
                {humanFriendlyCurrency(value)}
            </span>
        </div>
    )
}

export function AgentUsageSettings(): JSX.Element {
    const { totals, topModels, spendLoading, spendFailed } = useValues(agentUsageLogic)
    const { loadSpend } = useActions(agentUsageLogic)

    if (spendFailed) {
        return (
            <LemonBanner
                type="warning"
                action={{ children: 'Try again', onClick: loadSpend, loading: spendLoading }}
                className="max-w-200"
            >
                Your agent spend did not load.
            </LemonBanner>
        )
    }

    if (!totals) {
        return (
            <div className="flex flex-col gap-2 max-w-200">
                <LemonSkeleton className="h-16" />
                <LemonSkeleton className="h-24" />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4 max-w-200">
            <div className="flex flex-wrap gap-4 rounded border p-4 bg-surface-primary">
                <SpendStat label="Today" value={totals.todayUsd} />
                <SpendStat label="This month" value={totals.monthUsd} />
                <SpendStat label={`Last ${AGENT_SPEND_WINDOW_DAYS} days`} value={totals.windowUsd} />
            </div>
            {topModels.length > 0 ? (
                <LemonTable
                    size="small"
                    dataSource={topModels}
                    rowKey={(row) => row.model ?? 'other'}
                    columns={[
                        {
                            title: 'Model',
                            key: 'model',
                            render: (_, row) => <span translate="no">{row.model ?? 'Other models'}</span>,
                        },
                        {
                            title: 'Model calls',
                            key: 'generation_count',
                            align: 'right',
                            render: (_, row) => <span translate="no">{row.generation_count.toLocaleString()}</span>,
                        },
                        {
                            title: 'Spend',
                            key: 'cost_usd',
                            align: 'right',
                            render: (_, row) => <span translate="no">{humanFriendlyCurrency(row.cost_usd)}</span>,
                        },
                    ]}
                />
            ) : (
                <p className="text-secondary mb-0">
                    You have no agent spend in the last {AGENT_SPEND_WINDOW_DAYS} days.
                </p>
            )}
            <div className="flex">
                <LemonButton type="secondary" size="small" to={urls.organizationBilling()}>
                    Manage billing
                </LemonButton>
            </div>
        </div>
    )
}
