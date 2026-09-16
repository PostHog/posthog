import clsx from 'clsx'

import { IconInfo, IconWarning } from '@posthog/icons'

import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'

import {
    HogQLFixEdit,
    PredicateIndexUsage,
    PredicateIndexVerdict,
    UnprunedTableScan,
} from '~/queries/schema/schema-general'

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
        return { text: total === 1 ? '1 filter reads every row' : `${total} filters read every row`, scanning: true }
    }
    return { text: `${scanning} of ${total} filters read every row`, scanning: true }
}

function summarize(predicates: PredicateIndexUsage[], scans: UnprunedTableScan[]): { text: string; warning: boolean } {
    const filters = summarizeFilters(predicates)

    // A missing time range leads the summary, because it decides how much of the table is opened at
    // all. A filter count cannot stand in front of it: every filter can have an index while the scan
    // still reads every partition.
    if (scans.length > 0) {
        return { text: ['No time range', filters?.text].filter(Boolean).join(' · '), warning: true }
    }
    return { text: filters?.text ?? '', warning: !!filters?.scanning }
}

interface QueryIndexUsageBarProps {
    predicates: PredicateIndexUsage[]
    /** Table scans with no bound on their partition key. */
    scans: UnprunedTableScan[]
    /** A refresh is in flight, so the report still describes the SQL the server last saw. */
    refreshing?: boolean
    onApplyFix?: (edits: HogQLFixEdit[]) => void
}

export function QueryIndexUsageBar({
    predicates,
    scans,
    refreshing,
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
                            {/* A stale report carries offsets into text the editor no longer holds, so the fix waits for the refresh. */}
                            <UnprunedScanNotice scans={scans} onApplyFix={refreshing ? undefined : onApplyFix} />
                            <QueryIndexUsageTable predicates={predicates} />
                        </>
                    ),
                },
            ]}
        />
    )
}
