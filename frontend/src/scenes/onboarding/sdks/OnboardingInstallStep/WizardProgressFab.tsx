import { useActions, useValues } from 'kea'

import { IconCheck, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { wizardProgressTrackerLogic } from './wizardProgressTrackerLogic'

/**
 * Onboarding-scoped floating action button. Renders whenever a wizard session
 * has been observed and the user has navigated away from the install step's
 * full panel. Dismissible only after the run reaches a terminal phase.
 *
 * Mounts `wizardProgressTrackerLogic` at the scene root so SSE stays connected
 * across step navigation.
 */
export function WizardProgressFab(): JSX.Element | null {
    const { displayState, latestSession, elapsedSeconds, dismissed, panelMounted } =
        useValues(wizardProgressTrackerLogic)
    const { dismiss } = useActions(wizardProgressTrackerLogic)

    if (dismissed || panelMounted || displayState === 'preTakeover') {
        return null
    }

    const isTerminal = displayState === 'completed' || displayState === 'error'
    const skill = latestSession?.skill_id

    const headline =
        displayState === 'completed'
            ? "PostHog's wired in"
            : displayState === 'error'
              ? 'Wizard ran into trouble'
              : displayState === 'connecting'
                ? 'Reconnecting…'
                : 'Wizard installing PostHog'

    const sub =
        displayState === 'completed' || displayState === 'error'
            ? skill
                ? `${skill}`
                : null
            : skill
              ? `${skill} · ${formatElapsed(elapsedSeconds)}`
              : formatElapsed(elapsedSeconds)

    return (
        <div className="fixed bottom-4 right-4 z-[60] font-mono">
            <div
                role="status"
                aria-live="polite"
                className={`flex items-center gap-3 pl-3 pr-2 py-2 rounded-full shadow-2xl shadow-black/30 border ${
                    displayState === 'completed'
                        ? 'bg-success text-white border-success'
                        : displayState === 'error'
                          ? 'bg-brand-red text-white border-brand-red'
                          : 'bg-neutral-950 text-neutral-100 border-neutral-800'
                }`}
            >
                <FabIcon displayState={displayState} />
                <div className="flex flex-col leading-tight pr-1 min-w-0">
                    <span className="text-xs uppercase tracking-wider opacity-80">{headline}</span>
                    {sub ? <span className="text-[11px] tabular-nums truncate max-w-[180px]">{sub}</span> : null}
                </div>
                {isTerminal && (
                    <LemonButton
                        size="xsmall"
                        icon={<IconX />}
                        onClick={dismiss}
                        aria-label="Dismiss"
                        tooltip="Dismiss"
                        className="opacity-80 hover:opacity-100"
                    />
                )}
            </div>
            <FabKeyframes />
        </div>
    )
}

function FabIcon({ displayState }: { displayState: string }): JSX.Element {
    if (displayState === 'completed') {
        return (
            <span aria-hidden className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-white/20">
                <IconCheck className="text-white" />
            </span>
        )
    }
    if (displayState === 'error') {
        return (
            <span aria-hidden className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-white/20">
                <IconX className="text-white" />
            </span>
        )
    }
    return <span aria-hidden className="inline-block w-3 h-3 rounded-full bg-brand-red wizard-fab-pulse-dot shrink-0" />
}

function FabKeyframes(): JSX.Element {
    return (
        <style>{`
            @keyframes wizard-fab-pulse-dot {
                0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(245, 78, 0, 0.55); }
                50% { opacity: 0.6; box-shadow: 0 0 0 5px rgba(245, 78, 0, 0); }
            }
            .wizard-fab-pulse-dot { animation: wizard-fab-pulse-dot 1.6s ease-in-out infinite; }
        `}</style>
    )
}

function formatElapsed(seconds: number): string {
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m}:${s.toString().padStart(2, '0')}`
}
