import { useActions, useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { BurningMoneyHog, DetectiveHog } from 'lib/components/hedgehogs'

import { Query } from '~/queries/Query/Query'

import { AccountBillingKind, accountBillingLogic } from './accountBillingLogic'

const KIND_NOTE: Record<AccountBillingKind, string | null> = {
    usage: null,
    spend: 'Daily billed units (not dollars).',
}

function BillingInsightNotFound({ kind }: { kind: AccountBillingKind }): JSX.Element {
    const Hog = kind === 'spend' ? BurningMoneyHog : DetectiveHog
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
    const { savedInsight, savedInsightLoading, dateRange, variableOverrides } = useValues(logic)
    const { setDateRange } = useActions(logic)

    if (!externalId) {
        return <div className="p-4 text-secondary">This account has no linked organization.</div>
    }

    if (savedInsightLoading) {
        return <LemonSkeleton className="h-64 w-full" />
    }

    const query = savedInsight?.query
    if (!query) {
        return <BillingInsightNotFound kind={kind} />
    }

    const note = KIND_NOTE[kind]

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
                <DateFilter
                    dateFrom={dateRange.date_from}
                    dateTo={dateRange.date_to}
                    onChange={(from, to) => setDateRange(from, to)}
                />
                {note ? <span className="text-xs text-secondary">{note}</span> : null}
            </div>
            {/* Embedded DataVisualization collapses to a sliver without a fixed-height parent (InsightCard__viz is flex:1, min-height:0). */}
            <div className="h-80 flex flex-col overflow-hidden">
                <Query
                    uniqueKey={`account-billing-${accountId}-${kind}`}
                    query={query}
                    variablesOverride={variableOverrides ?? null}
                    readOnly
                    embedded
                />
            </div>
        </div>
    )
}
