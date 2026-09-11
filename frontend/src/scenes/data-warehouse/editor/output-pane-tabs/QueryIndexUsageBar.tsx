import clsx from 'clsx'

import { IconInfo, IconWarning } from '@posthog/icons'

import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'

import { EventsScanEstimate, PredicateIndexUsage } from '~/queries/schema/schema-general'

import { QueryIndexUsageTable } from './QueryIndexUsageTable'
import { summarizeQueryScan } from './queryScanSummary'

interface QueryIndexUsageBarProps {
    predicates: PredicateIndexUsage[]
    estimate?: EventsScanEstimate | null
    /** A refresh is in flight, so the report still describes the SQL the server last saw. */
    refreshing?: boolean
}

export function QueryIndexUsageBar({ predicates, estimate, refreshing }: QueryIndexUsageBarProps): JSX.Element | null {
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

    // With no filters there is nothing to expand, so the header stands alone instead of opening an empty panel.
    if (predicates.length === 0) {
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
                    content: <QueryIndexUsageTable predicates={predicates} />,
                },
            ]}
        />
    )
}
