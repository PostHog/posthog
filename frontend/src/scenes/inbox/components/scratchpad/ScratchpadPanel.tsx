import { useActions, useValues } from 'kea'

import { IconClock, IconNotebook, IconStack } from '@posthog/icons'
import { LemonInput, LemonSegmentedButton, LemonSkeleton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'

import { scratchpadLogic } from '../../logics/scratchpadLogic'
import { ScratchpadEntryCard } from './ScratchpadEntryCard'

/**
 * Browse + search surface for the scout fleet's durable memory (`SignalScratchpad`). Tells the
 * "scouts get smarter over time" story up top (what this is + how much has accumulated), then lets
 * the user read it newest-first or clustered by topic, and search it via the endpoint's ILIKE.
 *
 * Read-only: the harness writes memory on internal scope; humans inspect it here.
 */
export function ScratchpadPanel(): JSX.Element {
    const { entries, entriesLoading, totalCount, lastUpdatedAt, groups, searchText, grouping } =
        useValues(scratchpadLogic)
    const { setSearchText, setGrouping } = useActions(scratchpadLogic)

    const isInitialLoad = entriesLoading && entries === null
    const isSearching = searchText.trim().length > 0

    return (
        <div className="flex flex-col gap-4 px-4 py-3">
            <ScratchpadHeader totalCount={totalCount} lastUpdatedAt={lastUpdatedAt} />

            <div className="flex flex-wrap items-center gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search memory…"
                    value={searchText}
                    onChange={setSearchText}
                    className="flex-1 min-w-[12rem]"
                    allowClear
                />
                <LemonSegmentedButton
                    size="small"
                    value={grouping}
                    onChange={setGrouping}
                    options={[
                        { value: 'recent', label: 'Recent', icon: <IconClock /> },
                        { value: 'topic', label: 'By topic', icon: <IconStack /> },
                    ]}
                />
            </div>

            {isInitialLoad ? (
                <div className="flex flex-col gap-2">
                    <LemonSkeleton className="h-12 w-full rounded" />
                    <LemonSkeleton className="h-12 w-full rounded" />
                    <LemonSkeleton className="h-12 w-full rounded" />
                </div>
            ) : !entries || entries.length === 0 ? (
                <ScratchpadEmptyState isSearching={isSearching} />
            ) : grouping === 'topic' ? (
                <div className="flex flex-col gap-4">
                    {groups.map((group) => (
                        <div key={group.namespace} className="flex flex-col gap-2">
                            <div className="flex items-center gap-2">
                                <span className="text-xs font-medium uppercase tracking-wide text-default">
                                    {group.label}
                                </span>
                                <span className="text-[11px] text-muted">
                                    {pluralize(group.entries.length, 'note')}
                                </span>
                            </div>
                            {group.entries.map((entry) => (
                                <ScratchpadEntryCard key={entry.key} entry={entry} />
                            ))}
                        </div>
                    ))}
                </div>
            ) : (
                <div className="flex flex-col gap-2">
                    {entries.map((entry) => (
                        <ScratchpadEntryCard key={entry.key} entry={entry} />
                    ))}
                </div>
            )}
        </div>
    )
}

function ScratchpadHeader({
    totalCount,
    lastUpdatedAt,
}: {
    totalCount: number | null
    lastUpdatedAt: string | null
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
                <IconNotebook className="size-5 text-primary-3000" />
                <span className="text-base font-semibold text-default">Scout memory</span>
            </div>
            <p className="mb-0 max-w-2xl text-sm text-secondary">
                Durable notes your scouts keep so each run builds on what they already learned about this project —
                classifications, things they've ruled out, and the vocabulary they've settled on. This is how scouts get
                sharper over time instead of starting cold every run.
            </p>
            {totalCount !== null && totalCount > 0 && (
                <span className="text-xs text-muted">
                    {pluralize(totalCount, 'memory', 'memories')}
                    {lastUpdatedAt ? (
                        <>
                            {' · last updated '}
                            <TZLabel time={lastUpdatedAt} />
                        </>
                    ) : null}
                </span>
            )}
        </div>
    )
}

function ScratchpadEmptyState({ isSearching }: { isSearching: boolean }): JSX.Element {
    return (
        <div className="rounded border border-dashed border-primary bg-bg-light px-4 py-8 text-center text-sm text-muted">
            {isSearching
                ? 'No memories match your search.'
                : "Your scouts haven't recorded anything yet. As they run, what they learn shows up here."}
        </div>
    )
}
