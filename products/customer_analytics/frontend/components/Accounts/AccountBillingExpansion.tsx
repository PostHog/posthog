import { useActions, useValues } from 'kea'

import { HedgehogMagnifyingGlass } from '@posthog/brand/hoggies'
import { LemonSkeleton } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { BurningMoneyHog } from 'lib/components/hedgehogs'

import { Query } from '~/queries/Query/Query'

import { AccountBillingKind, accountBillingLogic } from './accountBillingLogic'

function BillingInsightNotFound({ kind }: { kind: AccountBillingKind }): JSX.Element {
    const Hog = kind === 'spend' ? BurningMoneyHog : HedgehogMagnifyingGlass
    return (
        <div className="flex flex-col items-center justify-center gap-2 p-8 text-center">
            <Hog className="w-24 h-24" />
            <h4 className="mb-0">No billing {kind} insight here</h4>
            <p className="text-secondary max-w-sm mb-0">
                We couldn't find the saved billing {kind} insight in this environment.
            </p>
        </div>
    )
}

export function AccountBillingExpansion({
    accountId,
    externalId,
    kind,
}: {
    accountId: string
    externalId: string
    kind: AccountBillingKind
}): JSX.Element {
    const logic = accountBillingLogic({ accountId, externalId, kind })
    const { savedInsights, savedInsightsLoading, dateRange, variableOverridesByShortId, queryKeyFor } = useValues(logic)
    const { setDateRange } = useActions(logic)

    if (!externalId) {
        return <div className="p-4 text-secondary">This account has no linked organization.</div>
    }

    if (savedInsightsLoading) {
        return <LemonSkeleton className="h-64 w-full" />
    }

    if (!savedInsights || savedInsights.length === 0) {
        return <BillingInsightNotFound kind={kind} />
    }

    const showTitles = savedInsights.length > 1

    return (
        <div className="flex flex-col gap-3">
            <DateFilter
                dateFrom={dateRange.date_from}
                dateTo={dateRange.date_to}
                onChange={(from, to) => setDateRange(from, to)}
            />
            {savedInsights.map((insight) => {
                const queryKey = queryKeyFor(insight.short_id)
                return (
                    <div key={insight.short_id} className="flex flex-col gap-1">
                        {showTitles && insight.name ? <h4 className="mb-0 text-sm">{insight.name}</h4> : null}
                        {/* Embedded DataVisualization collapses to a sliver without a fixed-height parent (InsightCard__viz is flex:1, min-height:0). */}
                        <div className="h-80 flex flex-col overflow-hidden">
                            <Query
                                key={queryKey}
                                uniqueKey={queryKey}
                                query={insight.query}
                                variablesOverride={variableOverridesByShortId[insight.short_id] ?? null}
                                readOnly
                                embedded
                                // Attach the insight's data logic to accountBillingLogic (mounted at the expanded-row
                                // root) so the loaded results survive tab switches instead of refetching on return.
                                attachTo={logic}
                            />
                        </div>
                    </div>
                )
            })}
        </div>
    )
}
