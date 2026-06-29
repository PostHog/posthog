import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { inboxSceneLogic } from '../../../inboxSceneLogic'
import { scoutDetailLogic } from '../../../logics/scoutDetailLogic'
import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { SCOUT_RUNS_WINDOW_SPAN, scoutRunsWindowLabel } from '../../../utils/scoutRunsWindow'
import { ScoutEmissionCard } from './ScoutEmissionCard'
import { ScoutReportCard } from './ScoutReportCard'
import { ScoutRowCard } from './ScoutRowCard'
import { ScoutRunHistorySection } from './ScoutRunHistorySection'

/**
 * Full-width scout detail surface, rendered over the inbox list at `/inbox/scouts/:skillName`.
 * Skeleton (W1): back link, the shared `ScoutRowCard` as the header, and the recent-window
 * rollup line. The Signals section (emission cards) and per-scout run history land next (W2/W3).
 */
export function ScoutDetailView({ skillName }: { skillName: string }): JSX.Element {
    const { scoutConfigs, rollups, runsWindowComplete } = useValues(scoutFleetLogic)
    const { updateScoutConfig, startRunsPolling, stopRunsPolling } = useActions(scoutFleetLogic)
    const { setSelectedScoutSkillName } = useActions(inboxSceneLogic)

    // Deep-linking straight to a scout (or a narrow viewport where the fleet list isn't mounted)
    // means nobody else is polling the runs window, so the header + rollup would read empty
    // defaults. Drive the same start/stop lifecycle the fleet section uses.
    useEffect(() => {
        startRunsPolling()
        return () => stopRunsPolling()
    }, [startRunsPolling, stopRunsPolling])

    const config = scoutConfigs?.find((c) => c.skill_name === skillName) ?? null
    const rollup = rollups.get(skillName)

    return (
        <div className="flex flex-col min-h-0 flex-1 overflow-auto gap-4 px-4 py-3">
            <LemonButton
                type="tertiary"
                size="small"
                icon={<IconArrowLeft />}
                onClick={() => setSelectedScoutSkillName(null)}
                className="self-start"
            >
                Scouts
            </LemonButton>

            {scoutConfigs === null ? (
                // Configs unresolved (loading, not-yet-fetched on a fresh deep-link mount, or a failed
                // load — never an empty fleet, which is `[]`). Hold the skeleton so "Scout not found"
                // can't flash before we actually have the fleet to look in.
                <LemonSkeleton className="h-16 w-full rounded" />
            ) : config === null ? (
                <div className="flex flex-1 items-center justify-center text-sm text-tertiary">Scout not found.</div>
            ) : (
                <>
                    <ScoutRowCard config={config} rollup={rollup} onUpdate={updateScoutConfig} asHeader />

                    {config.description ? (
                        <p className="text-sm text-secondary leading-snug mb-0">{config.description}</p>
                    ) : null}

                    <div className="flex flex-col gap-1">
                        <span className="text-xs font-medium text-default uppercase tracking-wide">
                            Last {SCOUT_RUNS_WINDOW_SPAN}
                        </span>
                        <span className="text-sm text-secondary">
                            {rollup && rollup.runCount > 0 ? (
                                <>
                                    {pluralize(rollup.runCount, 'run')} · {rollup.completedCount} completed ·{' '}
                                    {rollup.failedCount} failed · {pluralize(rollup.emittedCount, 'signal')} emitted
                                    {rollup.authoredReportIds.size > 0 && (
                                        <> · {pluralize(rollup.authoredReportIds.size, 'report')} authored</>
                                    )}
                                    {rollup.editedReportIds.size > 0 && (
                                        <> · {pluralize(rollup.editedReportIds.size, 'report')} edited</>
                                    )}
                                </>
                            ) : (
                                'No runs in this window.'
                            )}
                            {!runsWindowComplete && (
                                <span className="text-muted"> · {scoutRunsWindowLabel(runsWindowComplete)}</span>
                            )}
                        </span>
                    </div>

                    <ScoutReportsSection skillName={skillName} />

                    <ScoutSignalsSection skillName={skillName} />

                    <ScoutRunHistorySection skillName={skillName} />
                </>
            )}
        </div>
    )
}

/**
 * The Reports section: the inbox reports this scout authored or edited directly via the report
 * channel (`emit_report` / `edit_report`) in the recent window, newest-updated first. Distinct from
 * the Signals section, which lists weak `emit_signal` findings. Hidden entirely for the common scout
 * that never authors a report, so it only appears for report-channel scouts.
 */
function ScoutReportsSection({ skillName }: { skillName: string }): JSX.Element | null {
    const { reportRows, touchedReports, scoutReportsLoading, runsWindowLoadedOnce } = useValues(
        scoutDetailLogic({ skillName })
    )

    // Most scouts never author a report — keep the section out entirely rather than show an empty box.
    if (touchedReports.length === 0) {
        return null
    }

    const loading = !runsWindowLoadedOnce || (scoutReportsLoading && reportRows.length === 0)

    return (
        <div className="flex flex-col gap-2">
            <span className="text-xs font-medium text-default uppercase tracking-wide">Reports</span>
            {loading ? (
                <LemonSkeleton className="h-12 w-full rounded" />
            ) : reportRows.length === 0 ? (
                // Touched ids exist but none resolved — the reports were deleted, or the fetch failed.
                <div className="rounded border border-dashed border-primary bg-bg-light px-4 py-6 text-center text-sm text-muted">
                    Couldn’t load the reports this scout authored.
                </div>
            ) : (
                reportRows.map(({ report, action }) => (
                    <ScoutReportCard key={report.id} report={report} action={action} />
                ))
            )}
        </div>
    )
}

/**
 * The Signals section: every finding this scout emitted in the recent window, newest first.
 * Emissions are fetched per emitted run by `scoutDetailLogic` (keyed by skill) off the fleet's
 * already-polled runs window. Most runs are quiet, so an empty list is the healthy default.
 */
function ScoutSignalsSection({ skillName }: { skillName: string }): JSX.Element {
    const { emissionRows, emissionsLoading, emissionsLoadFailed, runsWindowLoadedOnce, runsWindowComplete } = useValues(
        scoutDetailLogic({ skillName })
    )
    const { selectedScoutFindingId } = useValues(inboxSceneLogic)

    // "Loading" until the fleet's runs window has settled once AND this scout's emissions have
    // resolved — otherwise a fresh deep-link would flash the empty state before we know the
    // emitted runs. Gating on the fleet's first-load flag (not its per-poll loading) keeps the
    // quiet-scout empty state from flickering to a skeleton every 60s poll.
    const loading = !runsWindowLoadedOnce || emissionsLoading
    const hasRows = emissionRows.length > 0
    // The unique emission the deep-link resolves to: the newest row whose finding matches.
    const deepLinkedEmissionId = selectedScoutFindingId
        ? (emissionRows.find(({ emission }) => emission.finding_id === selectedScoutFindingId)?.emission.id ?? null)
        : null

    return (
        <div className="flex flex-col gap-2">
            <span className="text-xs font-medium text-default uppercase tracking-wide">Signals</span>
            {loading && !hasRows ? (
                <LemonSkeleton className="h-12 w-full rounded" />
            ) : emissionsLoadFailed && !hasRows ? (
                // Every per-run emissions fetch failed while the rollup says these runs emitted —
                // don't claim "no signals". The 60s poll keeps retrying.
                <div className="rounded border border-dashed border-primary bg-bg-light px-4 py-6 text-center text-sm text-muted">
                    Couldn’t load signals for this scout. Retrying…
                </div>
            ) : !hasRows ? (
                <div className="rounded border border-dashed border-primary bg-bg-light px-4 py-6 text-center text-sm text-muted">
                    {runsWindowComplete
                        ? `No signals emitted in the last ${SCOUT_RUNS_WINDOW_SPAN}.`
                        : `No signals emitted in the recent runs we could load (the last ${SCOUT_RUNS_WINDOW_SPAN} is truncated).`}
                </div>
            ) : (
                <>
                    {emissionRows.map(({ emission, run, report }) => (
                        <ScoutEmissionCard
                            key={emission.id}
                            skillName={skillName}
                            emission={emission}
                            run={run}
                            report={report}
                            // `finding_id` repeats across runs (it's a dedup trace id, not unique), so only
                            // mark the newest matching emission — rows are newest-first — to keep the
                            // highlight/scroll deterministic for a single shared link.
                            isDeepLinked={emission.id === deepLinkedEmissionId}
                        />
                    ))}
                    {!runsWindowComplete && (
                        <span className="text-xs text-muted">
                            Older signals beyond the loaded {SCOUT_RUNS_WINDOW_SPAN} window aren’t shown.
                        </span>
                    )}
                </>
            )}
        </div>
    )
}
