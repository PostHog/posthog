import { IconInfo, IconWarning } from '@posthog/icons'

import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'

import { PredicateIndexUsage, PredicateIndexVerdict } from '~/queries/schema/schema-general'

import { QueryIndexUsageTable } from './QueryIndexUsageTable'

function summarize(predicates: PredicateIndexUsage[]): { text: string; scanning: boolean } {
    const total = predicates.length
    const scanning = predicates.filter((predicate) => predicate.verdict !== PredicateIndexVerdict.Indexed).length

    if (scanning === 0) {
        return { text: total === 1 ? '1 filter uses an index' : `All ${total} filters use an index`, scanning: false }
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
}

export function QueryIndexUsageBar({ predicates }: QueryIndexUsageBarProps): JSX.Element | null {
    if (predicates.length === 0) {
        return null
    }

    const { text, scanning } = summarize(predicates)

    return (
        <LemonCollapse
            embedded
            size="small"
            className="border-b rounded-none"
            panels={[
                {
                    key: 'index-usage',
                    dataAttr: 'sql-editor-index-usage',
                    header: (
                        <span className="flex items-center gap-2 text-xs">
                            {scanning ? (
                                <IconWarning className="text-warning" />
                            ) : (
                                <IconInfo className="text-secondary" />
                            )}
                            {text}
                        </span>
                    ),
                    content: <QueryIndexUsageTable predicates={predicates} />,
                },
            ]}
        />
    )
}
