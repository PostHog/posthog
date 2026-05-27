import { useActions, useValues } from 'kea'

import { IconSparkles, IconX } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { OnboardingStepKey } from '~/types'

import { onboardingLogic } from '../../onboardingLogic'
import { type DisplayState, wizardProgressTrackerLogic } from './wizardProgressTrackerLogic'

const RING_SIZE = 44
const RING_STROKE = 4
const RING_RADIUS = (RING_SIZE - RING_STROKE) / 2
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS

/**
 * Persistent corner widget that surfaces an in-flight wizard run while the user
 * navigates the rest of onboarding. Disappears when the install step is mounted
 * (the full panel takes over) and again once the user dismisses a terminal run.
 *
 * Click anywhere on the card to jump back to the install step.
 *
 * Gated on the same flag as the takeover panel so control-arm users don't mount
 * the sync logic (and open an SSE connection) at the scene level.
 */
export function WizardProgressFab(): JSX.Element | null {
    const isSyncEnabled = useFeatureFlag('ONBOARDING_WIZARD_SYNC', 'test')
    if (!isSyncEnabled) {
        return null
    }
    return <WizardProgressFabInner />
}

function WizardProgressFabInner(): JSX.Element | null {
    const { displayState, latestSession, elapsedSeconds, dismissed, panelMounted } =
        useValues(wizardProgressTrackerLogic)
    const { dismiss } = useActions(wizardProgressTrackerLogic)
    const { setStepId } = useActions(onboardingLogic)

    if (dismissed || panelMounted || displayState === 'preTakeover') {
        return null
    }

    const tasks = latestSession?.tasks ?? []
    const totalCount = tasks.length
    const completedCount = tasks.filter((t) => t.status === 'completed').length
    const progressPct = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0
    const currentTask = tasks.find((t) => t.status === 'in_progress')?.title

    const isTerminal = displayState === 'completed' || displayState === 'error'

    const handleExpand = (): void => {
        setStepId(OnboardingStepKey.INSTALL)
    }

    return (
        <div className="fixed bottom-5 right-5 z-[60] wizard-fab-slide-in">
            <FabKeyframes />
            <div
                role="status"
                aria-live="polite"
                className="relative w-[300px] bg-bg-light rounded-xl shadow-xl shadow-black/15 border border-border overflow-hidden"
            >
                <button
                    type="button"
                    onClick={handleExpand}
                    className="w-full text-left flex items-center gap-3 px-3 py-3 hover:bg-bg-3000 transition-colors"
                    aria-label="Return to the wizard install panel"
                >
                    <ProgressRing
                        progress={displayState === 'completed' ? 100 : progressPct}
                        state={displayState}
                        hasTasks={totalCount > 0}
                    />
                    <div className="flex-1 min-w-0 leading-tight">
                        <div className="flex items-center gap-1 text-xs uppercase tracking-wider text-muted font-semibold">
                            <IconSparkles className="text-sm wizard-fab-sparkle" aria-hidden />
                            <span>Setup wizard</span>
                        </div>
                        <div className="text-sm font-semibold text-default truncate mt-0.5">
                            {headlineFor(displayState)}
                        </div>
                        <div className="text-xs text-muted truncate mt-0.5 tabular-nums">
                            {subLineFor(displayState, currentTask, elapsedSeconds)}
                        </div>
                    </div>
                </button>
                {isTerminal ? (
                    <button
                        type="button"
                        onClick={(e) => {
                            e.stopPropagation()
                            dismiss()
                        }}
                        aria-label="Dismiss"
                        className="absolute top-1.5 right-1.5 p-1 rounded-md text-muted hover:text-default hover:bg-bg-3000 transition-colors"
                    >
                        <IconX className="text-base" />
                    </button>
                ) : null}
                <ProgressBar
                    progress={displayState === 'completed' ? 100 : progressPct}
                    state={displayState}
                    hasTasks={totalCount > 0}
                />
            </div>
        </div>
    )
}

function ProgressRing({
    progress,
    state,
    hasTasks,
}: {
    progress: number
    state: DisplayState
    hasTasks: boolean
}): JSX.Element {
    const accent = accentColor(state)
    const isIndeterminate = state === 'connecting' || (state === 'running' && !hasTasks)
    const dashOffset = RING_CIRCUMFERENCE * (1 - progress / 100)

    return (
        <div
            className="relative shrink-0 flex items-center justify-center"
            style={{ width: RING_SIZE, height: RING_SIZE }}
        >
            <svg width={RING_SIZE} height={RING_SIZE} viewBox={`0 0 ${RING_SIZE} ${RING_SIZE}`}>
                <circle
                    cx={RING_SIZE / 2}
                    cy={RING_SIZE / 2}
                    r={RING_RADIUS}
                    fill="none"
                    stroke="currentColor"
                    className="text-border"
                    strokeWidth={RING_STROKE}
                />
                {isIndeterminate ? (
                    <g className="wizard-fab-ring-spin" style={{ transformOrigin: '50% 50%' }}>
                        <circle
                            cx={RING_SIZE / 2}
                            cy={RING_SIZE / 2}
                            r={RING_RADIUS}
                            fill="none"
                            stroke={accent}
                            strokeWidth={RING_STROKE}
                            strokeLinecap="round"
                            strokeDasharray={`${RING_CIRCUMFERENCE * 0.25} ${RING_CIRCUMFERENCE}`}
                            transform={`rotate(-90 ${RING_SIZE / 2} ${RING_SIZE / 2})`}
                        />
                    </g>
                ) : (
                    <circle
                        cx={RING_SIZE / 2}
                        cy={RING_SIZE / 2}
                        r={RING_RADIUS}
                        fill="none"
                        stroke={accent}
                        strokeWidth={RING_STROKE}
                        strokeLinecap="round"
                        strokeDasharray={RING_CIRCUMFERENCE}
                        strokeDashoffset={dashOffset}
                        transform={`rotate(-90 ${RING_SIZE / 2} ${RING_SIZE / 2})`}
                        style={{ transition: 'stroke-dashoffset 600ms ease-out' }}
                    />
                )}
            </svg>
            <span className="absolute inset-0 flex items-center justify-center text-[11px] font-semibold tabular-nums">
                <RingCenter state={state} progress={progress} hasTasks={hasTasks} accent={accent} />
            </span>
        </div>
    )
}

function RingCenter({
    state,
    progress,
    hasTasks,
    accent,
}: {
    state: DisplayState
    progress: number
    hasTasks: boolean
    accent: string
}): JSX.Element {
    if (state === 'completed') {
        return (
            <span style={{ color: accent }} aria-hidden>
                ✓
            </span>
        )
    }
    if (state === 'error') {
        return (
            <span style={{ color: accent }} aria-hidden>
                ✗
            </span>
        )
    }
    if (state === 'connecting' || !hasTasks) {
        return <span aria-hidden />
    }
    return <span style={{ color: accent }}>{`${progress}%`}</span>
}

function ProgressBar({
    progress,
    state,
    hasTasks,
}: {
    progress: number
    state: DisplayState
    hasTasks: boolean
}): JSX.Element | null {
    if (!hasTasks && state !== 'completed') {
        return null
    }
    const isTerminal = state === 'completed' || state === 'error'
    return (
        <div className="h-1 bg-bg-3000 relative" aria-hidden>
            <div
                className={`absolute inset-y-0 left-0 transition-[width] duration-500 ${
                    isTerminal ? '' : 'wizard-fab-shimmer'
                }`}
                style={{
                    width: `${progress}%`,
                    ...(isTerminal ? { background: accentColor(state) } : {}),
                }}
            />
        </div>
    )
}

function headlineFor(state: DisplayState): string {
    switch (state) {
        case 'completed':
            return 'PostHog is set up'
        case 'error':
            return 'Wizard hit a snag'
        case 'connecting':
            return 'Reconnecting…'
        default:
            return 'Installing PostHog'
    }
}

function subLineFor(state: DisplayState, currentTask: string | undefined, elapsedSeconds: number): string {
    if (state === 'completed') {
        return 'tap to see what was set up'
    }
    if (state === 'error') {
        return 'tap to open and retry'
    }
    if (state === 'connecting') {
        return 'restoring connection to the wizard'
    }
    const elapsed = formatElapsed(elapsedSeconds)
    if (currentTask) {
        return `${currentTask} · ${elapsed}`
    }
    return `running for ${elapsed}`
}

function accentColor(state: DisplayState): string {
    if (state === 'completed') {
        return 'rgb(16, 185, 129)' // emerald-500
    }
    return 'rgb(245, 78, 0)' // brand-red — used for running, connecting, and error
}

function formatElapsed(seconds: number): string {
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m}:${s.toString().padStart(2, '0')}`
}

function FabKeyframes(): JSX.Element {
    return (
        <style>{`
            @keyframes wizard-fab-slide-in {
                from { opacity: 0; transform: translateY(12px); }
                to   { opacity: 1; transform: translateY(0); }
            }
            .wizard-fab-slide-in {
                animation: wizard-fab-slide-in 320ms ease-out both;
            }
            @keyframes wizard-fab-ring-spin {
                to { transform: rotate(360deg); }
            }
            .wizard-fab-ring-spin {
                animation: wizard-fab-ring-spin 1.2s linear infinite;
                transform-box: fill-box;
            }
            /* Soft wizard-rainbow shimmer on the running progress bar — saturated
               enough to read as "magical", muted enough not to fight the headline. */
            @keyframes wizard-fab-shimmer {
                0%   { background-position: 0% 50%; }
                100% { background-position: 200% 50%; }
            }
            .wizard-fab-shimmer {
                background-image: linear-gradient(
                    90deg,
                    #f54e00 0%,
                    #ff8a3d 20%,
                    #ffc83d 40%,
                    #66d19e 60%,
                    #5b9dff 80%,
                    #b285ff 100%
                );
                background-size: 200% 100%;
                animation: wizard-fab-shimmer 5s linear infinite;
            }
            @keyframes wizard-fab-sparkle {
                0%, 60%, 100% { opacity: 1; transform: scale(1) rotate(0deg); }
                70%           { opacity: 0.4; transform: scale(0.85) rotate(-8deg); }
                85%           { opacity: 1; transform: scale(1.1) rotate(8deg); }
            }
            .wizard-fab-sparkle {
                color: #b285ff;
                animation: wizard-fab-sparkle 3.4s ease-in-out infinite;
                transform-origin: center;
            }
        `}</style>
    )
}
