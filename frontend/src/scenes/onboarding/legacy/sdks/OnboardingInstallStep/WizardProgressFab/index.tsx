import './WizardProgressFab.scss'

import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconX } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { wizardActiveSessionDetectorLogic } from '../../../../shared/wizard-sync/wizardActiveSessionDetectorLogic'
import { wizardProgressTrackerLogic } from '../wizardProgressTrackerLogic'
import { ExpandedDetails } from './ExpandedDetails'
import { headlineFor, simulatedTaskFraction, subLineFor } from './helpers'
import { ProgressRing } from './ProgressRing'

export function WizardProgressFab(): JSX.Element | null {
    const isSyncEnabled = useFeatureFlag('ONBOARDING_WIZARD_SYNC', 'test')
    if (!isSyncEnabled) {
        return null
    }
    return <WizardProgressFabGate />
}

// Gates whether we mount the streaming tracker logic at all. The detector does
// a cheap REST poll and only flips `shouldStream` once it has evidence that a
// wizard run is in flight — so the SSE connection isn't held open for every
// authenticated user just because the flag is on (INC-886).
function WizardProgressFabGate(): JSX.Element | null {
    const { shouldStream } = useValues(wizardActiveSessionDetectorLogic)
    if (!shouldStream) {
        return null
    }
    return <WizardProgressFabInner />
}

function WizardProgressFabInner(): JSX.Element | null {
    const {
        displayState,
        latestSession,
        elapsedSeconds,
        dismissed,
        panelMounted,
        sessionIsCurrent,
        taskStartedAt,
        now,
    } = useValues(wizardProgressTrackerLogic)
    const { dismiss } = useActions(wizardProgressTrackerLogic)
    const { reportWizardSyncProgressExpanded } = useActions(eventUsageLogic)

    const [expanded, setExpanded] = useState(false)

    if (dismissed || panelMounted || displayState === 'preTakeover' || !sessionIsCurrent) {
        return null
    }
    const tasks = latestSession?.tasks ?? []
    const totalCount = tasks.length
    const completedCount = tasks.filter((t) => t.status === 'completed').length
    const inProgressTask = tasks.find((t) => t.status === 'in_progress')
    const currentTask = inProgressTask?.title
    // Ring fill = real completed count plus a simulated fraction of the in-progress
    // task, so the ring keeps moving between backend updates.
    const inProgressFraction = inProgressTask ? simulatedTaskFraction(taskStartedAt[inProgressTask.id], now) : 0
    const progressPct = totalCount > 0 ? Math.round(((completedCount + inProgressFraction) / totalCount) * 100) : 0

    const isTerminal = displayState === 'completed' || displayState === 'error'

    return (
        <div className="fixed bottom-5 right-5 z-[60] wizard-fab-slide-in">
            <div
                role="status"
                aria-live="polite"
                className="relative w-[300px] bg-bg-light rounded-xl shadow-xl shadow-black/15 border border-border overflow-hidden"
            >
                <button
                    type="button"
                    onClick={() => {
                        const next = !expanded
                        setExpanded(next)
                        // Only the expand direction is an intentful "show me the details"
                        // signal worth tracking; collapsing is just tidying up.
                        if (next) {
                            reportWizardSyncProgressExpanded({
                                workflowId: latestSession?.workflow_id,
                                skillId: latestSession?.skill_id,
                                displayState,
                                progressPct,
                            })
                        }
                    }}
                    className="w-full text-left flex items-center gap-3 px-3 py-3 hover:bg-bg-3000 transition-colors cursor-pointer"
                    aria-label={expanded ? 'Collapse wizard details' : 'Expand wizard details'}
                    aria-expanded={expanded}
                >
                    <ProgressRing
                        progress={displayState === 'completed' ? 100 : progressPct}
                        state={displayState}
                        hasTasks={totalCount > 0}
                    />
                    <div className="flex-1 min-w-0 leading-tight">
                        <div className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-muted font-semibold">
                            <span>Setup wizard</span>
                        </div>
                        <div className="text-sm font-semibold text-default truncate mt-0.5">
                            {headlineFor(displayState)}
                        </div>
                        <div className="text-xs text-muted truncate mt-0.5 tabular-nums">
                            {subLineFor(displayState, currentTask, elapsedSeconds)}
                        </div>
                    </div>
                    <IconChevronDown
                        className={`text-base text-muted shrink-0 transition-transform duration-200 ${
                            expanded ? 'rotate-180' : ''
                        }`}
                        aria-hidden
                    />
                </button>
                {isTerminal ? (
                    <button
                        type="button"
                        onClick={(e) => {
                            e.stopPropagation()
                            dismiss()
                        }}
                        aria-label="Dismiss"
                        className="absolute top-1.5 right-1.5 p-1 rounded-md text-muted hover:text-default hover:bg-bg-3000 transition-colors z-10"
                    >
                        <IconX className="text-base" />
                    </button>
                ) : null}
                {expanded && (
                    <div className="grid grid-rows-[1fr]">
                        <div className="overflow-hidden">
                            <ExpandedDetails tasks={tasks} taskStartedAt={taskStartedAt} now={now} />
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}
