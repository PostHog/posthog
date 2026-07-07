import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'

import {
    FINDINGS_SCOUT_FILTER_ALL,
    FINDINGS_SEVERITY_FILTER_ALL,
    findingsLogic,
    FindingsSortKey,
} from '../../logics/findingsLogic'
import { SignalReportPriority } from '../../types'
import { SCOUT_RUNS_WINDOW_SPAN } from '../../utils/scoutRunsWindow'
import { ScoutEmissionCard } from '../config/scouts/ScoutEmissionCard'

const SEVERITY_OPTIONS: SignalReportPriority[] = ['P0', 'P1', 'P2', 'P3', 'P4']
const SORT_OPTIONS: { value: FindingsSortKey; label: string }[] = [
    { value: 'newest', label: 'Newest' },
    { value: 'oldest', label: 'Oldest' },
    { value: 'severity', label: 'Severity' },
    { value: 'confidence', label: 'Confidence' },
]

/**
 * Cross-fleet findings browser — every finding the troop emitted recently in one place, newest first,
 * searchable and filterable by scout/severity with a sort toggle. Reuses the per-scout
 * `ScoutEmissionCard` with `showScout` on. Read-only; acting on a finding happens in its inbox report.
 */
export function FindingsPanel(): JSX.Element {
    const {
        filteredRows,
        availableScouts,
        totalCount,
        scoutCount,
        latestEmittedAt,
        searchText,
        scoutFilter,
        severityFilter,
        sortKey,
        hasLoadedOnce,
        emissionsLoadFailed,
        emissionsLoading,
    } = useValues(findingsLogic)
    const { setSearchText, setScoutFilter, setSeverityFilter, setSortKey, loadEmissions } = useActions(findingsLogic)

    const isFiltering =
        searchText.trim().length > 0 ||
        scoutFilter !== FINDINGS_SCOUT_FILTER_ALL ||
        severityFilter !== FINDINGS_SEVERITY_FILTER_ALL

    return (
        <div className="flex flex-col gap-4 px-4 py-3">
            <FindingsHeader totalCount={totalCount} scoutCount={scoutCount} latestEmittedAt={latestEmittedAt} />

            <div className="flex flex-wrap items-center gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search findings…"
                    value={searchText}
                    onChange={setSearchText}
                    className="flex-1 min-w-[12rem]"
                    allowClear
                />
                <LemonSelect
                    size="small"
                    value={scoutFilter}
                    onChange={setScoutFilter}
                    options={[
                        { value: FINDINGS_SCOUT_FILTER_ALL, label: 'All scouts' },
                        ...availableScouts.map((scout) => ({
                            value: scout.skillName,
                            label: `${scout.label} (${scout.count})`,
                        })),
                    ]}
                />
                <LemonSelect
                    size="small"
                    value={severityFilter}
                    onChange={setSeverityFilter}
                    options={[
                        { value: FINDINGS_SEVERITY_FILTER_ALL, label: 'All severities' },
                        ...SEVERITY_OPTIONS.map((severity) => ({ value: severity, label: severity })),
                    ]}
                />
                <LemonSelect
                    size="small"
                    value={sortKey}
                    onChange={setSortKey}
                    options={SORT_OPTIONS}
                    // `renderButtonContent` is handed the selected leaf, not its label string — read
                    // `leaf.label` so the button reads "Sort: Newest" rather than "Sort: [object Object]".
                    renderButtonContent={(leaf) => <>Sort: {leaf?.label ?? ''}</>}
                />
            </div>

            {hasLoadedOnce && emissionsLoadFailed && totalCount > 0 && (
                // A later poll/retry of the batched fetch failed while a prior set is still on screen
                // (stale). The list a user triages against may be incomplete — warn rather than show it
                // silently.
                <LemonBanner
                    type="warning"
                    action={{ children: 'Retry', onClick: () => loadEmissions(), loading: emissionsLoading }}
                >
                    Some findings couldn't be loaded, so this list may be incomplete.
                </LemonBanner>
            )}

            {!hasLoadedOnce ? (
                <div className="flex flex-col gap-2">
                    <LemonSkeleton className="h-14 w-full rounded" />
                    <LemonSkeleton className="h-14 w-full rounded" />
                    <LemonSkeleton className="h-14 w-full rounded" />
                </div>
            ) : emissionsLoadFailed && totalCount === 0 ? (
                <FindingsErrorState onRetry={() => loadEmissions()} loading={emissionsLoading} />
            ) : filteredRows.length === 0 ? (
                <FindingsEmptyState isFiltering={isFiltering} />
            ) : (
                <div className="flex flex-col gap-2">
                    {filteredRows.map((row) => (
                        <ScoutEmissionCard
                            // emission.id, not source_id — a run can re-emit a finding_id, sharing source_id.
                            key={row.emission.id}
                            skillName={row.run.skill_name}
                            emission={row.emission}
                            run={row.run}
                            report={row.report}
                            showScout
                        />
                    ))}
                </div>
            )}
        </div>
    )
}

function FindingsHeader({
    totalCount,
    scoutCount,
    latestEmittedAt,
}: {
    totalCount: number
    scoutCount: number
    latestEmittedAt: string | null
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
                <IconSparkles className="size-5 text-primary-3000" />
                <span className="text-base font-semibold text-default">Scout findings</span>
            </div>
            <p className="mb-0 text-sm text-secondary">
                Every signal your scouts have emitted recently, in one place — newest first. See what's been surfaced
                across the whole troop, which scout found it, and the inbox report it fed into.
            </p>
            {totalCount > 0 && (
                <span className="text-xs text-muted">
                    {pluralize(totalCount, 'finding')} · {pluralize(scoutCount, 'scout')}
                    {latestEmittedAt ? (
                        <>
                            {' · latest '}
                            <TZLabel time={latestEmittedAt} />
                        </>
                    ) : null}
                </span>
            )}
            <span className="text-xs text-muted">
                Covers findings from the most recent {SCOUT_RUNS_WINDOW_SPAN} of troop runs. Older findings live on in
                the inbox reports they produced.
            </span>
        </div>
    )
}

function FindingsErrorState({ onRetry, loading }: { onRetry: () => void; loading: boolean }): JSX.Element {
    return (
        <div className="flex flex-col items-center gap-2 rounded border border-dashed border-primary bg-bg-light px-4 py-8 text-center text-sm text-muted">
            <span>
                Couldn't load findings. The scout API may be unavailable or this project may not be enrolled yet.
            </span>
            <LemonButton type="secondary" size="small" onClick={onRetry} loading={loading}>
                Retry
            </LemonButton>
        </div>
    )
}

function FindingsEmptyState({ isFiltering }: { isFiltering: boolean }): JSX.Element {
    return (
        <div className="rounded border border-dashed border-primary bg-bg-light px-4 py-8 text-center text-sm text-muted">
            {isFiltering
                ? 'No findings match your search and filters.'
                : "Your scouts haven't emitted any findings yet. As they scan your project, what they surface shows up here."}
        </div>
    )
}
