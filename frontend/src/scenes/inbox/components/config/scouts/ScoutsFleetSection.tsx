import { useActions, useValues } from 'kea'

import { IconChevronDown, IconCompass, IconPlus, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

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
import { ScoutHelperSkillLinks } from './ScoutHelperSkillLinks'
import { ScoutRowCard } from './ScoutRowCard'

/**
 * Expandable scout troop manager, hosted in the Scout troop setup modal. Collapsed it is a
 * one-line pulse; expanded it lists every scout with inline config controls.
 * Cloud port of desktop's `ScoutsFleetSection`.
 */
export function ScoutsFleetSection(): JSX.Element {
    const { scoutConfigs, scoutConfigsLoading, expanded, enabledCount, lastRunAt } = useValues(scoutFleetLogic)
    const { setExpanded, loadScoutConfigs } = useActions(scoutFleetLogic)

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
        return <ScoutsEmptyState />
    }

    return (
        <div className="flex flex-col gap-3">
            <button
                type="button"
                onClick={() => setExpanded(!expanded)}
                aria-expanded={expanded}
                className="flex w-full items-center justify-between gap-3 rounded border border-primary bg-bg-light px-4 py-3.5 text-left transition-colors hover:border-primary-3000 hover:bg-bg-3000"
            >
                <div className="flex items-center gap-3 min-w-0">
                    <IconCompass className="size-5 shrink-0 text-primary-3000" />
                    <div className="flex flex-col min-w-0">
                        <span className="font-medium text-sm text-default">Scout troop</span>
                        <span className="text-xs text-secondary leading-snug">
                            {enabledCount} of {scoutConfigs.length} scouts enabled
                            {lastRunAt ? (
                                <>
                                    {' · last dispatched '}
                                    <TZLabel time={lastRunAt} />
                                </>
                            ) : null}
                        </span>
                    </div>
                </div>
                <IconChevronDown
                    className={`size-4 shrink-0 text-muted transition-transform ${expanded ? '' : '-rotate-90'}`}
                />
            </button>
            {expanded ? <ScoutsFleetList /> : null}
        </div>
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

function ScoutsFleetList(): JSX.Element {
    const { visibleConfigs, rollups, fleetSummary, hideDisabled, runsWindowComplete } = useValues(scoutFleetLogic)
    const { setHideDisabled, updateScoutConfig } = useActions(scoutFleetLogic)

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs text-secondary">
                    {summarize(fleetSummary)}
                    <span className="text-muted"> · {scoutRunsWindowLabel(runsWindowComplete)}</span>
                </span>
                <span className="flex-1" />
                <LemonButton size="xsmall" type="tertiary" onClick={() => setHideDisabled(!hideDisabled)}>
                    {hideDisabled ? 'Show disabled' : 'Hide disabled'}
                </LemonButton>
            </div>

            <div className="flex items-center gap-2 flex-wrap">
                <ScoutChatCta label="How is my scout troop performing?" prompt={SCOUT_FLEET_OVERVIEW_PROMPT} />
                <ScoutChatCta label="What signals were emitted recently?" prompt={SCOUT_RECENT_SIGNALS_PROMPT} />
                <ScoutChatCta label="Make a scout" prompt={SCOUT_AUTHOR_PROMPT} icon={<IconPlus />} />
            </div>

            {/* Bounded to roughly 10 rows; larger troops scroll within the section. */}
            <div className="max-h-[710px] overflow-y-auto">
                <div className="flex flex-col gap-2">
                    {visibleConfigs.map((config: SignalScoutConfig) => (
                        <ScoutRowCard
                            key={config.id}
                            config={config}
                            rollup={rollups.get(config.skill_name)}
                            onUpdate={updateScoutConfig}
                        />
                    ))}
                </div>
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
    const { chatTaskRunning } = useValues(scoutFleetLogic)
    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={icon ?? <IconSparkles />}
            loading={chatTaskRunning}
            disabledReason={chatTaskRunning ? 'Starting a task…' : undefined}
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
