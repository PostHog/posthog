import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconCompass, IconPlus, IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { inboxSceneLogic } from '../../../inboxSceneLogic'
import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { SignalScoutConfig } from '../../../types'
import {
    FleetSummary,
    SCOUT_AUTHOR_PROMPT,
    SCOUT_FLEET_OVERVIEW_PROMPT,
    SCOUT_RECENT_SIGNALS_PROMPT,
    SCOUT_RUNS_WINDOW_SPAN,
    scoutRunsWindowLabel,
} from '../../../utils/scoutRunsWindow'
import { agentSetupModalLogic } from '../../shell/agentSetupModalLogic'
import { FleetFindingsCallout } from './FleetFindingsCallout'
import { FleetMemoryCallout } from './FleetMemoryCallout'
import { ScoutHelperSkillLinks } from './ScoutHelperSkillLinks'
import { ScoutRowCard } from './ScoutRowCard'

/**
 * Scout troop manager, hosted in the Scout troop setup modal (and the Agents settings tab). Both
 * hosts already title the section "Scout troop", so this always shows the full fleet: a stats
 * header (roster + run pulse) followed by every scout with inline config controls.
 * Cloud port of desktop's `ScoutsFleetSection`.
 */
export function ScoutsFleetSection(): JSX.Element {
    const { scoutConfigs, scoutConfigsLoading } = useValues(scoutFleetLogic)
    const { loadScoutConfigs, startRunsPolling, stopRunsPolling } = useActions(scoutFleetLogic)
    const { setScratchpadOpen, setFindingsOpen } = useActions(inboxSceneLogic)
    const { closeSetupModal } = useActions(agentSetupModalLogic)

    // Poll the runs window only while the fleet list is open — the always-mounted setup
    // widget reads configs only and shouldn't trigger the paginated runs requests.
    useEffect(() => {
        startRunsPolling()
        return () => stopRunsPolling()
    }, [startRunsPolling, stopRunsPolling])

    if (scoutConfigsLoading && scoutConfigs === null) {
        return <LemonSkeleton className="h-12 w-full rounded" />
    }

    // A failed request must not masquerade as an empty troop – a missing scope or
    // regional rollout gap would otherwise be indistinguishable from "no scouts yet".
    if (scoutConfigs === null) {
        return (
            <div className="flex items-center gap-3 rounded border border-danger bg-danger-highlight px-4 py-3.5">
                <span className="flex-1 text-xs text-danger">
                    Couldn't load the scout troop. The scout API may be unavailable or this project may not be enrolled
                    yet.
                </span>
                <LemonButton type="secondary" size="small" status="danger" onClick={() => loadScoutConfigs()}>
                    Retry
                </LemonButton>
            </div>
        )
    }

    if (scoutConfigs.length === 0) {
        return (
            <div className="flex flex-col gap-3">
                <ScoutAlphaBanner />
                <ScoutsEmptyState />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-3">
            <ScoutAlphaBanner />
            <FleetStatsHeader />
            <FleetFindingsCallout
                onOpen={() => {
                    // This section can render inside the scout-troop setup modal; dismiss it so the
                    // findings view isn't left hidden behind the portal'd modal. No-op outside a modal.
                    closeSetupModal()
                    setFindingsOpen(true)
                }}
            />
            <FleetMemoryCallout
                onOpen={() => {
                    // This section can render inside the scout-troop setup modal; dismiss it so the
                    // memory view isn't left hidden behind the portal'd modal. No-op outside a modal.
                    closeSetupModal()
                    setScratchpadOpen(true)
                }}
            />
            <ScoutsFleetList />
        </div>
    )
}

/**
 * Alpha/announcement banner for the scout troop, sourced from the `signals-scout` flag payload via
 * the metadata endpoint — so the copy (e.g. a run-limit notice) can change with no deploy. Renders
 * nothing when no message is set. Dismissal is remembered per-message, so a reworded notice resurfaces.
 */
function ScoutAlphaBanner(): JSX.Element | null {
    const { scoutBannerMessage } = useValues(scoutFleetLogic)
    if (!scoutBannerMessage) {
        return null
    }
    return (
        <LemonBanner type="info" dismissKey={`signals-scout-banner-${scoutBannerMessage}`}>
            {scoutBannerMessage}
        </LemonBanner>
    )
}

/** One-line fleet pulse: running, success rate, signals emitted + emit rate. */
function summarize(summary: FleetSummary | null): string {
    if (!summary) {
        return 'None running now'
    }
    const parts = [summary.runningCount > 0 ? `${summary.runningCount} running now` : 'None running now']
    if (summary.successRate !== null) {
        parts.push(`${percentage(summary.successRate, 0)} success`)
    }
    const emittedPart =
        summary.emitRate !== null
            ? `${pluralize(summary.emittedCount, 'signal')} emitted (${percentage(summary.emitRate, 0)})`
            : `${pluralize(summary.emittedCount, 'signal')} emitted`
    parts.push(emittedPart)
    return parts.join(' · ')
}

/**
 * Top-of-modal troop summary: roster (enabled / total + last dispatched) over the run pulse
 * (running / success / signals emitted across the window). Sits above the toggle row so the modal
 * leads with "what the troop is" before its controls.
 */
function FleetStatsHeader(): JSX.Element {
    const { scoutConfigs, enabledCount, lastRunAt, fleetSummary, runsWindowComplete } = useValues(scoutFleetLogic)

    return (
        <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-medium text-default">
                    {enabledCount} of {scoutConfigs?.length ?? enabledCount} scouts enabled
                </span>
                {lastRunAt ? (
                    <span className="text-xs text-secondary">
                        last dispatched <TZLabel time={lastRunAt} />
                    </span>
                ) : null}
            </div>
            <span className="text-xs text-muted">
                {summarize(fleetSummary)} · {scoutRunsWindowLabel(runsWindowComplete)}
            </span>
        </div>
    )
}

function ScoutsFleetList(): JSX.Element {
    const { visibleConfigs, rollups, hideDisabled, deletingScoutIds } = useValues(scoutFleetLogic)
    const { setHideDisabled, updateScoutConfig, deleteScout } = useActions(scoutFleetLogic)

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2 flex-wrap">
                <ScoutChatCta label="How is my scout troop performing?" prompt={SCOUT_FLEET_OVERVIEW_PROMPT} />
                <ScoutChatCta label="What signals were emitted recently?" prompt={SCOUT_RECENT_SIGNALS_PROMPT} />
                <ScoutChatCta label="Make a scout" prompt={SCOUT_AUTHOR_PROMPT} icon={<IconPlus />} />
                <span className="flex-1" />
                <LemonButton size="xsmall" type="tertiary" onClick={() => setHideDisabled(!hideDisabled)}>
                    {hideDisabled ? 'Show disabled' : 'Hide disabled'}
                </LemonButton>
            </div>

            {/* The enclosing modal owns the scroll, so the list stays flat here — a nested
                overflow container would create a scroll-area-within-a-scroll-area. */}
            <div className="flex flex-col gap-2">
                {visibleConfigs.map((config: SignalScoutConfig) => (
                    <ScoutRowCard
                        key={config.id}
                        config={config}
                        rollup={rollups.get(config.skill_name)}
                        onUpdate={updateScoutConfig}
                        onDelete={deleteScout}
                        deleting={deletingScoutIds.includes(config.id)}
                    />
                ))}
            </div>

            <div className="flex flex-col gap-1">
                <span className="text-xs text-muted">
                    Run counts and emitted totals cover the last {SCOUT_RUNS_WINDOW_SPAN} of troop runs. New scouts are
                    created as <span className="font-mono text-[11px]">signals-scout-*</span> skills in your PostHog
                    project.
                </span>
                <ScoutHelperSkillLinks />
            </div>
        </div>
    )
}

/**
 * Suggestion-chip CTA that fires an auto-mode cloud task asking a templated
 * question, then navigates to it – same one-click shape as the inbox
 * discuss / create-PR flows.
 */
function ScoutChatCta({ label, prompt, icon }: { label: string; prompt: string; icon?: JSX.Element }): JSX.Element {
    const { startScoutChatTask } = useActions(scoutFleetLogic)
    const { runningChatPrompt } = useValues(scoutFleetLogic)
    const isRunning = runningChatPrompt === prompt
    const anyRunning = runningChatPrompt !== null
    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={icon ?? <IconSparkles />}
            loading={isRunning}
            disabledReason={anyRunning ? 'Starting a task…' : undefined}
            onClick={() => startScoutChatTask(prompt, label, label)}
        >
            {label}
        </LemonButton>
    )
}

function ScoutsEmptyState(): JSX.Element {
    return (
        <div className="flex flex-col items-start gap-2 rounded border border-primary bg-bg-light px-5 py-5">
            <div className="flex items-center gap-2">
                <IconCompass className="size-[18px] text-primary-3000" />
                <span className="font-medium text-sm text-default">No scouts on this project yet</span>
            </div>
            <p className="max-w-2xl text-xs text-secondary leading-snug mb-0">
                Scouts are rolling out gradually. Once your project is enrolled, the canonical troop appears here
                automatically and you can add custom scouts by creating{' '}
                <span className="font-mono text-[11px]">signals-scout-*</span> skills in PostHog.
            </p>
            <ScoutHelperSkillLinks />
        </div>
    )
}
