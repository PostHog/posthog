import { useActions, useValues } from 'kea'

import {
    LemonButton,
    LemonCheckbox,
    LemonColorGlyph,
    LemonInput,
    LemonSegmentedButton,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
    LemonTag,
} from '@posthog/lemon-ui'

import { type AccountContextFact, type FactConfidence, topicColor } from './accountContextData'
import { AccountContextDate } from './AccountContextDate'
import { accountContextLogic, type AccountContextLogicProps } from './accountContextLogic'
import { CONTEXT_WRITE_DISABLED_REASON } from './constants'

const FACT_PAGE_SIZE = 10

function filterOptions(values: string[], allLabel: string): { value: string | null; label: string }[] {
    return [{ value: null, label: allLabel }, ...values.map((value) => ({ value, label: value }))]
}

function shownTopics(topics: string[], topicFilter: string | null): string[] {
    const ordered = topicFilter ? [topicFilter, ...topics.filter((topic) => topic !== topicFilter)] : topics
    return ordered.slice(0, 2)
}

export function AccountContextFacts({
    logicProps,
    embedded,
}: {
    logicProps: AccountContextLogicProps
    embedded: boolean
}): JSX.Element {
    const logic = accountContextLogic(logicProps)
    const {
        visibleFacts,
        factConfidence,
        confidenceCounts,
        factSearch,
        filterOptions: options,
        topicFilter,
        authorFilter,
        sourceFilter,
        recheckOnly,
        recheckCount,
    } = useValues(logic)
    const { setFactConfidence, setFactSearch, setTopicFilter, setAuthorFilter, setSourceFilter, setRecheckOnly } =
        useActions(logic)

    const columns: LemonTableColumns<AccountContextFact> = [
        {
            title: 'Fact',
            key: 'text',
            render: (_, fact) => (
                <div className="flex flex-col gap-1 py-1">
                    <span>{fact.text}</span>
                    {fact.needsRecheck ? (
                        <div className="flex flex-wrap items-center gap-2">
                            <LemonTag type="warning">Needs a recheck</LemonTag>
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                disabledReason={CONTEXT_WRITE_DISABLED_REASON}
                                data-attr="account-context-mark-still-true"
                            >
                                Mark as still true
                            </LemonButton>
                        </div>
                    ) : null}
                </div>
            ),
        },
        {
            title: 'Topic',
            key: 'topics',
            render: (_, fact) => (
                <div className="flex flex-wrap gap-1">
                    {shownTopics(fact.topics, topicFilter).map((topic) => (
                        <LemonTag key={topic} icon={<LemonColorGlyph colorToken={topicColor(topic)} size="small" />}>
                            {topic}
                        </LemonTag>
                    ))}
                </div>
            ),
        },
        {
            title: 'Source',
            key: 'source',
            render: (_, fact) => <span className="whitespace-nowrap">{fact.source || 'Unknown'}</span>,
        },
        {
            title: 'By',
            key: 'author',
            render: (_, fact) => <span className="whitespace-nowrap">{fact.author || 'Unknown'}</span>,
        },
        {
            title: 'Captured',
            key: 'capturedOn',
            render: (_, fact) => (
                <span className="whitespace-nowrap">
                    <AccountContextDate date={fact.capturedOn} />
                </span>
            ),
        },
        {
            key: 'actions',
            width: 0,
            render: (_, fact) => (
                <div className="flex justify-end gap-1 whitespace-nowrap">
                    {fact.confirmed ? null : (
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            disabledReason={CONTEXT_WRITE_DISABLED_REASON}
                            data-attr="account-context-confirm-fact"
                        >
                            Confirm
                        </LemonButton>
                    )}
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        disabledReason={CONTEXT_WRITE_DISABLED_REASON}
                        data-attr="account-context-dispute-fact"
                    >
                        Dispute
                    </LemonButton>
                </div>
            ),
        },
    ]

    return (
        <section className="flex flex-col gap-2" data-attr="account-context-facts">
            <h4 className="mb-0">Facts</h4>
            <div className="flex flex-wrap items-center gap-2">
                <LemonSegmentedButton<FactConfidence>
                    size="small"
                    value={factConfidence}
                    onChange={setFactConfidence}
                    options={[
                        { value: 'confirmed', label: `Confirmed (${confidenceCounts.confirmed})` },
                        { value: 'inferred', label: `Inferred (${confidenceCounts.inferred})` },
                    ]}
                />
                <LemonInput
                    type="search"
                    size="small"
                    placeholder="Search facts"
                    value={factSearch}
                    onChange={setFactSearch}
                    className="min-w-48"
                />
                <LemonSelect
                    size="small"
                    value={topicFilter}
                    onChange={setTopicFilter}
                    options={filterOptions(options.topics, 'All topics')}
                    data-attr="account-context-topic-filter"
                    menu={{ className: 'ph-no-capture' }}
                />
                <LemonSelect
                    size="small"
                    value={authorFilter}
                    onChange={setAuthorFilter}
                    options={filterOptions(options.authors, 'Anyone')}
                    data-attr="account-context-author-filter"
                    menu={{ className: 'ph-no-capture' }}
                />
                <LemonSelect
                    size="small"
                    value={sourceFilter}
                    onChange={setSourceFilter}
                    options={filterOptions(options.sources, 'All sources')}
                    data-attr="account-context-source-filter"
                    menu={{ className: 'ph-no-capture' }}
                />
                <LemonCheckbox
                    checked={recheckOnly}
                    onChange={setRecheckOnly}
                    label={`Needs a recheck (${recheckCount})`}
                    data-attr="account-context-recheck-filter"
                />
            </div>
            <LemonTable<AccountContextFact>
                size="small"
                embedded={embedded}
                dataSource={visibleFacts}
                columns={columns}
                rowKey="id"
                key={[factConfidence, factSearch, topicFilter, authorFilter, sourceFilter, recheckOnly].join('|')}
                pagination={{ pageSize: FACT_PAGE_SIZE, useUrl: false }}
                emptyState="No facts match these filters."
            />
        </section>
    )
}
