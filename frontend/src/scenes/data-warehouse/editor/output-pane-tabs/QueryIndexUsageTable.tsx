import { LemonTable } from '@posthog/lemon-ui'

import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'

import { PredicateIndexUsage, PredicateIndexVerdict, PredicateScope } from '~/queries/schema/schema-general'

// `Indexed` is deliberately not a success tag. It means an index covers the comparison, which is a
// schema fact; whether granules are actually dropped depends on data we do not look at.
const VERDICT_TAGS: Record<PredicateIndexVerdict, { type: LemonTagType; label: string }> = {
    [PredicateIndexVerdict.Indexed]: { type: 'default', label: 'Index applies' },
    [PredicateIndexVerdict.Blocked]: { type: 'danger', label: 'Index unused' },
    [PredicateIndexVerdict.UnindexedColumn]: { type: 'warning', label: 'Column scan' },
    [PredicateIndexVerdict.UnindexedJson]: { type: 'warning', label: 'JSON scan' },
    [PredicateIndexVerdict.OperatorNotIndexable]: { type: 'muted', label: 'Full scan' },
}

const INDEX_LABELS: Record<string, string> = {
    minmax: 'min-max',
    bloom_filter: 'bloom filter',
    ngram_lower: 'n-gram',
    bloom_filter_lower: 'bloom filter',
}

// Scope prefixes tell `properties.x` apart from `person.properties.x`; event properties are the
// common case and read fine unprefixed.
const SCOPE_PREFIXES: Partial<Record<PredicateScope, string>> = {
    [PredicateScope.Person]: 'person.',
    [PredicateScope.Group]: 'group.',
}

interface QueryIndexUsageTableProps {
    predicates: PredicateIndexUsage[]
}

export function QueryIndexUsageTable({ predicates }: QueryIndexUsageTableProps): JSX.Element | null {
    if (predicates.length === 0) {
        return null
    }

    return (
        <>
            <p className="text-xs px-2 pt-1 mb-1">
                How each property filter reads its data. A filter with no index behind it reads every row.
            </p>
            <LemonTable
                size="small"
                dataSource={predicates}
                expandable={{
                    expandedRowRender: (predicate) => (
                        <div className="flex flex-col gap-1 px-2 py-1 text-xs">
                            <p className="mb-0">{predicate.message}</p>
                            {predicate.fix && <p className="mb-0 font-semibold">{predicate.fix}</p>}
                        </div>
                    ),
                }}
                columns={[
                    {
                        key: 'filter',
                        title: 'Filter',
                        render: (_, { property_name, operator, scope }) => (
                            <code className="text-xs">
                                {SCOPE_PREFIXES[scope] ?? ''}
                                {property_name} {operator === '==' ? '=' : operator} …
                            </code>
                        ),
                    },
                    {
                        key: 'source',
                        title: 'Reads from',
                        // The physical column name is on the response but stays out of the UI: it is not
                        // something a reader can select, create or drop.
                        render: (_, { source_label }) => <span className="text-xs">{source_label}</span>,
                    },
                    {
                        key: 'index',
                        title: 'Index',
                        render: (_, { usable_indexes }) =>
                            usable_indexes.length > 0 ? (
                                <span className="text-xs">
                                    {[...new Set(usable_indexes.map((index) => INDEX_LABELS[index] ?? index))].join(
                                        ', '
                                    )}
                                </span>
                            ) : (
                                <span className="text-secondary text-xs">None</span>
                            ),
                    },
                    {
                        key: 'verdict',
                        title: 'Reads',
                        render: (_, { verdict }) => (
                            <LemonTag type={VERDICT_TAGS[verdict].type}>{VERDICT_TAGS[verdict].label}</LemonTag>
                        ),
                    },
                ]}
            />
        </>
    )
}
