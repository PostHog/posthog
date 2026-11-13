import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonCard, LemonCollapse, LemonInput, LemonTag } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ResourceTagFilter } from '../components/ResourceTagFilter'
import { compositeInputsLogic } from './compositeInputsLogic'

export function ScorerDependents({ definitionId, count }: { definitionId: string; count: number }): JSX.Element {
    const logic = compositeInputsLogic({ id: `dependents-${definitionId}`, inputDefinitionId: definitionId })
    const { options, optionsLoading, optionsError, search, tagFilters } = useValues(logic)
    const { setSearch, setTagFilters, loadOptions } = useActions(logic)
    return (
        <LemonCard
            hoverEffect={false}
            className="p-3 bg-[var(--color-bg-fill-info-tertiary)] border-[var(--color-border-info)]"
        >
            <LemonCollapse
                embedded
                size="small"
                panels={[
                    {
                        key: 'dependents',
                        header: {
                            className: '!bg-transparent !px-0',
                            children: (
                                <span className="flex flex-col gap-1 text-left">
                                    <span className="flex flex-wrap items-center gap-2">
                                        <span>Used by composite scores</span>
                                        <LemonTag type="info" size="small" weight="normal">
                                            {count}
                                        </LemonTag>
                                    </span>
                                    <span className="text-xs text-muted font-normal">
                                        These composite scores keep using their selected version of this scorer until
                                        you update them.
                                    </span>
                                </span>
                            ),
                        },
                        dataAttr: 'aio-scorer-dependent-composites',
                        className: '!p-0',
                        bodyClassName: '!border-0',
                        content: (
                            <div className="flex flex-col gap-2 pt-3">
                                <div className="flex flex-wrap items-center gap-2">
                                    <LemonInput
                                        type="search"
                                        size="xsmall"
                                        className="w-40 max-w-full text-xs"
                                        value={search}
                                        onChange={setSearch}
                                        onPressEnter={(event) => event.preventDefault()}
                                        placeholder="Search scores"
                                        aria-label="Search dependent composite scores"
                                        data-attr="aio-scorer-dependent-search"
                                    />
                                    <ResourceTagFilter size="xsmall" filters={tagFilters} onChange={setTagFilters} />
                                </div>
                                {optionsLoading ? (
                                    <p className="mb-0 text-sm text-muted">Loading composite scores…</p>
                                ) : optionsError ? (
                                    <LemonBanner
                                        type="error"
                                        action={{
                                            children: 'Try again',
                                            onClick: loadOptions,
                                            'data-attr': 'aio-scorer-dependent-retry',
                                        }}
                                    >
                                        Could not load composite scores.
                                    </LemonBanner>
                                ) : !options?.results.length ? (
                                    <p className="mb-0 text-sm text-muted">No matching composite scores.</p>
                                ) : (
                                    <ul className="list-none m-0 p-0 flex flex-wrap gap-2 max-h-48 overflow-y-auto">
                                        {options?.results.map((scorer) => (
                                            <li key={scorer.id} className="min-w-0 max-w-full">
                                                <LemonButton
                                                    type="secondary"
                                                    size="xsmall"
                                                    className="max-w-full"
                                                    to={urls.aiObservabilityScorer(scorer.id)}
                                                    targetBlank
                                                    tooltip={`${scorer.name} · Open in a new tab`}
                                                    data-attr="aio-scorer-dependent-open"
                                                >
                                                    <span className="truncate">{scorer.name}</span>
                                                </LemonButton>
                                            </li>
                                        ))}
                                    </ul>
                                )}
                                {!optionsLoading &&
                                    !optionsError &&
                                    options &&
                                    options.count > options.results.length && (
                                        <p className="mb-0 text-sm text-muted">
                                            Showing {options.results.length} of {options.count} matches. Refine your
                                            search or tags to find another composite score.
                                        </p>
                                    )}
                            </div>
                        ),
                    },
                ]}
            />
        </LemonCard>
    )
}
