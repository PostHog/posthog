import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import hogWelder from 'public/hedgehog/hog-welder.png'
import starHog from 'public/hedgehog/star-hog.png'
import warningHog from 'public/hedgehog/warning-hog.png'

import { type DisplayState, wizardProgressTrackerLogic } from './wizardProgressTrackerLogic'

/**
 * Onboarding-scoped floating widget. Persists across onboarding step navigation
 * while a wizard session is in flight, with a hog mascot + labelled status so
 * users understand what they're looking at. Dismissible only after a terminal phase.
 */
export function WizardProgressFab(): JSX.Element | null {
    const { displayState, latestSession, elapsedSeconds, dismissed, panelMounted } =
        useValues(wizardProgressTrackerLogic)
    const { dismiss } = useActions(wizardProgressTrackerLogic)

    if (dismissed || panelMounted || displayState === 'preTakeover') {
        return null
    }

    const isTerminal = displayState === 'completed' || displayState === 'error'
    const isRunning = !isTerminal
    const skill = latestSession?.skill_id
    const headline = headlineFor(displayState)
    const sub = subFor(displayState, skill, elapsedSeconds)
    const accent = accentColor(displayState)
    const mascot = mascotFor(displayState)

    return (
        <div className="fixed bottom-5 right-5 z-[60]">
            <FabKeyframes />
            <div
                role="status"
                aria-live="polite"
                className="flex items-center gap-3 pl-2 pr-4 py-2 rounded-full bg-bg-light shadow-2xl shadow-black/20 border border-border min-w-[300px]"
                style={{ borderColor: accent }}
            >
                <span
                    className={`relative flex-shrink-0 w-16 h-16 rounded-full flex items-center justify-center ${
                        isRunning ? 'wizard-fab-glow' : ''
                    }`}
                    style={{ background: `${accent}1a` }}
                >
                    <img
                        src={mascot}
                        alt=""
                        draggable={false}
                        className={`relative w-12 h-12 object-contain ${isRunning ? 'wizard-fab-mascot-bob' : ''}`}
                    />
                </span>
                <div className="flex flex-col leading-tight min-w-0 flex-1">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">Setup wizard</span>
                    <span className="text-sm font-semibold text-default truncate" style={{ color: accent }}>
                        {headline}
                    </span>
                    {sub ? <span className="text-xs text-muted tabular-nums truncate">{sub}</span> : null}
                </div>
                {isTerminal && (
                    <LemonButton
                        size="xsmall"
                        icon={<IconX />}
                        onClick={dismiss}
                        aria-label="Dismiss"
                        tooltip="Dismiss"
                    />
                )}
            </div>
        </div>
    )
}

function headlineFor(state: DisplayState): string {
    switch (state) {
        case 'completed':
            return "PostHog's wired in"
        case 'error':
            return 'Hit a snag'
        case 'connecting':
            return 'Reconnecting…'
        default:
            return 'Installing PostHog'
    }
}

function subFor(state: DisplayState, skill: string | undefined, elapsedSeconds: number): string | null {
    if (state === 'completed') {
        return skill ? `${skill} · all set` : 'all set'
    }
    if (state === 'error') {
        return skill ? `${skill} · open the panel to retry` : 'open the panel to retry'
    }
    const elapsed = formatElapsed(elapsedSeconds)
    return skill ? `${skill} · ${elapsed}` : elapsed
}

function mascotFor(state: DisplayState): string {
    switch (state) {
        case 'completed':
            return starHog
        case 'error':
            return warningHog
        default:
            return hogWelder
    }
}

function accentColor(state: DisplayState): string {
    switch (state) {
        case 'completed':
            return 'rgb(16, 185, 129)' // emerald-500
        case 'error':
            return 'rgb(245, 78, 0)' // brand-red
        default:
            return 'rgb(245, 78, 0)' // brand-red
    }
}

function FabKeyframes(): JSX.Element {
    return (
        <style>{`
            @keyframes wizard-fab-mascot-bob {
                0%, 100% { transform: translateY(0) rotate(-2deg); }
                50%      { transform: translateY(-3px) rotate(2deg); }
            }
            .wizard-fab-mascot-bob {
                animation: wizard-fab-mascot-bob 1.6s ease-in-out infinite;
            }
            @keyframes wizard-fab-glow {
                0%, 100% { box-shadow: 0 0 0 0 rgba(245, 78, 0, 0.45); }
                50%      { box-shadow: 0 0 0 8px rgba(245, 78, 0, 0); }
            }
            .wizard-fab-glow {
                animation: wizard-fab-glow 2.2s ease-in-out infinite;
            }
        `}</style>
    )
}

function formatElapsed(seconds: number): string {
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m}:${s.toString().padStart(2, '0')}`
}
