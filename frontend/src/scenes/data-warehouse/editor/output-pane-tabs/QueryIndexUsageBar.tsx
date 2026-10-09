import clsx from 'clsx'

import { IconInfo, IconWarning } from '@posthog/icons'

import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'

import { HogQLFixEdit, PredicateIndexUsage, PredicateIndexVerdict, PredicateQuickfix, UnprunedTableScan } from '~/queries/schema/schema-general'

import { QueryIndexUsageTable } from './QueryIndexUsageTable'
import { UnprunedScanNotice } from './UnprunedScanNotice'

function summarizeFilters(predicates: PredicateIndexUsage[]): { text: string; scanning: boolean } | null {
    const total = predicates.length
    if (total === 0) {
        return null
    }
    const scanning = predicates.filter((predicate) => predicate.verdict !== PredicateIndexVerdict.Indexed).length

    // Says an index exists, not that the filter is cheap. Whether an index drops any data depends on
    // the table's sort order and the value being compared, which the report does not look at.
    if (scanning === 0) {
        return { text: total === 1 ? '1 filter has an index' : `All ${total} filters have an index`, scanning: false }
    }
    if (scanning === total) {
        return {
            text: total === 1 ? '1 filter reads every row' : `${total} filters read every row`,
            scanning: true,
        }
    }
    return { text: `${scanning} of ${total} filters read every row`, scanning: true }
}

function summarize(predicates: PredicateIndexUsage[], scans: UnprunedTableScan[]): { text: string; warning: boolean } {
    const filters = summarizeFilters(predicates)
    if (scans.length > 0) {
        return { text: ['No time range', filters?.text].filter(Boolean).join(' · '), warning: true }
    }
    return { text: filters?.text ?? '', warning: !!filters?.scanning }
}

interface QueryIndexUsageBarProps {
    predicates: PredicateIndexUsage[]
    scans: UnprunedTableScan[]
    /** A refresh is in flight, so the report still describes the SQL the server last saw. */
    refreshing?: boolean
    /** The report does not describe the text the editor holds, so its offsets would land elsewhere. */
    stale?: boolean
    onApplyQuickfix?: (quickfix: PredicateQuickfix) => void
    onFixWithAI?: (prompt: string) => void
    fixWithAILoading?: boolean
    onApplyFix?: (edits: HogQLFixEdit[]) => void
}

export function QueryIndexUsageBar({
    predicates,
    scans,
    refreshing,
    stale,
    onApplyQuickfix,
    onFixWithAI,
    fixWithAILoading,
    onApplyFix,
}: QueryIndexUsageBarProps): JSX.Element | null {
    if (predicates.length === 0 && scans.length === 0) {
        return null
    }

    const { text, warning } = summarize(predicates, scans)

    return (
        <LemonCollapse
            embedded
            size="small"
            className={clsx('border-b rounded-none', refreshing && 'opacity-60')}
            panels={[
                {
                    key: 'index-usage',
                    dataAttr: 'sql-editor-index-usage',
                    header: (
                        <span className="flex items-center gap-2 text-xs">
                            {refreshing || !warning ? (
                                <IconInfo className="text-secondary" />
                            ) : (
                                <IconWarning className="text-warning" />
                            )}
                            {refreshing ? 'Checking filters' : text}
                        </span>
                    ),
                    content: (
                        <>
                            <UnprunedScanNotice scans={scans} onApplyFix={refreshing || stale ? undefined : onApplyFix} />
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
