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
import { ScoutReportCard } from '../config/scouts/ScoutReportCard'

const SEVERITY_OPTIONS: SignalReportPriority[] = ['P0', 'P1', 'P2', 'P3', 'P4']
const SORT_OPTIONS: { value: FindingsSortKey; label: string }[] = [
    { value: 'newest', label: 'Newest' },
    { value: 'oldest', label: 'Oldest' },
    { value: 'severity', label: 'Severity' },
    { value: 'confidence', label: 'Confidence' },
]

/**
 * Cross-fleet findings browser — everything the troop surfaced recently in one place, newest first:
 * legacy `emit_signal` findings plus the inbox reports scouts authored/edited via the report channel.
 * Searchable and filterable by scout/severity with a sort toggle. Reuses the per-scout
 * `ScoutEmissionCard` / `ScoutReportCard` with scout attribution on. Read-only; acting on a finding
 * happens in its inbox report.
 */
export function FindingsPanel(): JSX.Element {
    const {
        filteredRows,
        filteredReportRows,
        reportRows,
        availableScouts,
        totalCount,
        authoredReportCount,
        editedReportCount,
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
    const hasReports = reportRows.length > 0

    return (
        <div className="flex flex-col gap-4 px-4 py-3">
            <FindingsHeader
                totalCount={totalCount}
                authoredReportCount={authoredReportCount}
                editedReportCount={editedReportCount}
                scoutCount={scoutCount}
                latestEmittedAt={latestEmittedAt}
            />

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

            {hasLoadedOnce &&
                emissionsLoadFailed &&
                totalCount > 0 && (
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
            ) : emissionsLoadFailed && totalCount === 0 && !hasReports ? (
                <FindingsErrorState onRetry={() => loadEmissions()} loading={emissionsLoading} />
            ) : totalCount === 0 && !hasReports ? (
                <FindingsEmptyState isFiltering={isFiltering} />
            ) : (
                <>
                    {/* Reports the fleet authored/edited via the report channel. Hidden entirely when
                        no report was touched, so the legacy findings-only layout stays flat. */}
                    {hasReports && (
                        <div className="flex flex-col gap-2">
                            <span className="text-xs font-medium text-default uppercase tracking-wide">Reports</span>
                            {filteredReportRows.length === 0 ? (
                                <div className="rounded border border-dashed border-primary bg-bg-light px-4 py-6 text-center text-sm text-muted">
                                    No reports match your search and filters.
                                </div>
                            ) : (
                                filteredReportRows.map((row) => (
                                    <ScoutReportCard
                                        key={row.report.id}
                                        report={row.report}
                                        action={row.action}
                                        skillName={row.skillName}
                                    />
                                ))
                            )}
                        </div>
                    )}

                    {/* Legacy emit_signal findings. When reports are also on screen the section gets a
                        heading; hidden when the fleet only produced reports (and nothing failed),
                        mirroring the per-scout detail view's hide-empty-section rule. */}
                    {(totalCount > 0 || emissionsLoadFailed) && (
                        <div className="flex flex-col gap-2">
                            {hasReports && (
                                <span className="text-xs font-medium text-default uppercase tracking-wide">
                                    Findings
                                </span>
                            )}
                            {emissionsLoadFailed && totalCount === 0 ? (
                                <FindingsErrorState onRetry={() => loadEmissions()} loading={emissionsLoading} />
                            ) : filteredRows.length === 0 ? (
                                <div className="rounded border border-dashed border-primary bg-bg-light px-4 py-6 text-center text-sm text-muted">
                                    No findings match your search and filters.
                                </div>
                            ) : (
                                filteredRows.map((row) => (
                                    <ScoutEmissionCard
                                        // emission.id, not source_id — a run can re-emit a finding_id, sharing source_id.
                                        key={row.emission.id}
                                        skillName={row.run.skill_name}
                                        emission={row.emission}
                                        run={row.run}
                                        report={row.report}
                                        showScout
                                    />
                                ))
                            )}
                        </div>
                    )}
                </>
            )}
        </div>
    )
}

function FindingsHeader({
    totalCount,
    authoredReportCount,
    editedReportCount,
    scoutCount,
    latestEmittedAt,
}: {
    totalCount: number
    authoredReportCount: number
    editedReportCount: number
    scoutCount: number
    latestEmittedAt: string | null
}): JSX.Element {
    const tallyParts: string[] = []
    if (totalCount > 0) {
        tallyParts.push(pluralize(totalCount, 'finding'))
    }
    if (authoredReportCount > 0) {
        tallyParts.push(`${pluralize(authoredReportCount, 'report')} authored`)
    }
    if (editedReportCount > 0) {
        tallyParts.push(`${pluralize(editedReportCount, 'report')} edited`)
    }
    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
                <IconSparkles className="size-5 text-primary-3000" />
                <span className="text-base font-semibold text-default">Scout findings</span>
            </div>
            <p className="mb-0 text-sm text-secondary">
                Everything your scouts have surfaced recently, in one place — newest first: the signals they emitted and
                the inbox reports they authored or edited. See what's been found across the whole troop and which scout
                found it.
            </p>
            {tallyParts.length > 0 && (
                <span className="text-xs text-muted">
                    {tallyParts.join(' · ')} · {pluralize(scoutCount, 'scout')}
                    {latestEmittedAt ? (
                        <>
                            {' · latest '}
                            <TZLabel time={latestEmittedAt} />
                        </>
                    ) : null}
                </span>
            )}
            <span className="text-xs text-muted">
                Covers the most recent {SCOUT_RUNS_WINDOW_SPAN} of troop runs. Older findings live on in the inbox
                reports they produced.
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
                ? 'No findings or reports match your search and filters.'
                : "Your scouts haven't surfaced anything yet. As they scan your project, the findings they emit and the reports they author show up here."}
        </div>
    )
}
