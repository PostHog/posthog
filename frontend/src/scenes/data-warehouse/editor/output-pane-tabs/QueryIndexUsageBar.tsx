import clsx from 'clsx'

import { IconInfo, IconWarning } from '@posthog/icons'

import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'

import { PredicateIndexUsage, PredicateIndexVerdict } from '~/queries/schema/schema-general'

import { QueryIndexUsageTable } from './QueryIndexUsageTable'

function summarize(predicates: PredicateIndexUsage[]): { text: string; scanning: boolean } {
    const total = predicates.length
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

interface QueryIndexUsageBarProps {
    predicates: PredicateIndexUsage[]
    /** A refresh is in flight, so the report still describes the SQL the server last saw. */
    refreshing?: boolean
}

export function QueryIndexUsageBar({ predicates, refreshing }: QueryIndexUsageBarProps): JSX.Element | null {
    if (predicates.length === 0) {
        return null
    }

    const { text, scanning } = summarize(predicates)

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
                            {refreshing || !scanning ? (
                                <IconInfo className="text-secondary" />
                            ) : (
                                <IconWarning className="text-warning" />
                            )}
                            {refreshing ? 'Checking filters' : text}
                        </span>
                    ),
                    content: <QueryIndexUsageTable predicates={predicates} />,
                },
            ]}
        />
    )
}
