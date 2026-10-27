import clsx from 'clsx'

import { IconInfo, IconWarning } from '@posthog/icons'

import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'

import {
    CostPlanStep,
    PredicateIndexUsage,
    PredicateQuickfix,
    ScanEstimate,
    ScanEstimateSource,
} from '~/queries/schema/schema-general'

import { QueryCostPlan } from './QueryCostPlan'
import { QueryIndexUsageTable } from './QueryIndexUsageTable'
import { summarizeQueryScan } from './queryScanSummary'
import { QueryScanTablesTable } from './QueryScanTablesTable'

interface QueryIndexUsageBarProps {
    predicates: PredicateIndexUsage[]
    estimate?: ScanEstimate | null
    /** The plan that explains the estimate. It replaces the per-table list; the filter table stays because it carries the quickfix actions. */
    plan?: CostPlanStep[] | null
    /** A refresh is in flight, so the report still describes the SQL the server last saw. */
    refreshing?: boolean
    /** The report does not describe the text the editor holds, so its offsets would land elsewhere. */
    stale?: boolean
    onApplyQuickfix?: (quickfix: PredicateQuickfix) => void
    onFixWithAI?: (prompt: string) => void
    fixWithAILoading?: boolean
}

export function QueryIndexUsageBar({
    predicates,
    estimate,
    plan,
    refreshing,
    stale,
    onApplyQuickfix,
    onFixWithAI,
    fixWithAILoading,
}: QueryIndexUsageBarProps): JSX.Element | null {
    const summary = summarizeQueryScan(predicates, estimate)
    if (!summary) {
        return null
    }

    const header = (
        <span className="flex items-center gap-2 text-xs">
            {!refreshing && summary.warn ? (
                <IconWarning className="text-warning" />
            ) : (
                <IconInfo className="text-secondary" />
            )}
            {refreshing ? 'Checking query' : summary.text}
        </span>
    )

    // A single events scan is fully described by the header, so the table list only appears when there is a
    // second table, or a table the header's number does not cover.
    const showTables =
        !!estimate &&
        (estimate.tables.length > 1 || estimate.tables.some((table) => table.source !== ScanEstimateSource.Events))

    const hasPlan = !!plan && plan.length > 0

    // With nothing to expand, the header stands alone instead of opening an empty panel.
    if (predicates.length === 0 && !showTables && !hasPlan) {
        return (
            <div
                className={clsx('border-b px-2 py-1.5', refreshing && 'opacity-60')}
                data-attr="sql-editor-index-usage"
            >
                {header}
            </div>
        )
    }

    return (
        <LemonCollapse
            embedded
            size="small"
            className={clsx('border-b rounded-none', refreshing && 'opacity-60')}
            panels={[
                {
                    key: 'index-usage',
                    dataAttr: 'sql-editor-index-usage',
                    header,
                    content: (
                        <>
                            {hasPlan && plan ? (
                                <QueryCostPlan steps={plan} />
                            ) : showTables && estimate ? (
                                <QueryScanTablesTable estimate={estimate} />
                            ) : null}
                            <QueryIndexUsageTable
                                predicates={predicates}
                                stale={stale}
                                onApplyQuickfix={onApplyQuickfix}
                                onFixWithAI={onFixWithAI}
                                fixWithAILoading={fixWithAILoading}
                            />
                        </>
                    ),
                },
            ]}
        />
    )
}
