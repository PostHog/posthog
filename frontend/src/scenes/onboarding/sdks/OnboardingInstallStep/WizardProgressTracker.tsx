import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { type ActivityEntry, type DisplayState, wizardProgressTrackerLogic } from './wizardProgressTrackerLogic'

/**
 * Wizard takeover panel — a "terminal in the browser" feel for the live
 * progress of an in-flight wizard run.
 *
 * Renders nothing until a wizard session is observed. The parent uses the
 * `useWizardTakeoverActive` hook to decide whether to swap the command card
 * for this panel.
 */
export function WizardProgressTracker({ onManualSetup }: { onManualSetup?: () => void } = {}): JSX.Element | null {
    const { displayState } = useValues(wizardProgressTrackerLogic)
    const { setPanelMounted } = useActions(wizardProgressTrackerLogic)

    useEffect(() => {
        setPanelMounted(true)
        return () => setPanelMounted(false)
    }, [setPanelMounted])

    if (displayState === 'preTakeover') {
        return null
    }

    const isCompleted = displayState === 'completed'

    return (
        <div className="w-full font-mono text-sm bg-neutral-950 text-neutral-100 rounded-lg border border-neutral-800 shadow-2xl shadow-black/30 overflow-hidden">
            <TerminalHeader />
            <StatusSubhead />
            {isCompleted ? (
                <div className="px-4 py-4 border-t border-neutral-800">
                    <CompletionRecap />
                </div>
            ) : (
                <>
                    <div className="px-4 py-3 border-t border-neutral-800">
                        <TaskList />
                    </div>
                    <div className="px-4 py-3 border-t border-neutral-800">
                        <ActivityLog />
                    </div>
                </>
            )}
            <Footer onManualSetup={onManualSetup} />
        </div>
    )
}

/**
 * Used by the parent variant to decide whether to render the takeover at all.
 * Mounts the logic on first call. Returns `true` once we have any session
 * state to display.
 */
export function useWizardTakeoverActive(): boolean {
    const { displayState } = useValues(wizardProgressTrackerLogic)
    return displayState !== 'preTakeover'
}

function TerminalHeader(): JSX.Element {
    const { latestSession, displayState, elapsedSeconds } = useValues(wizardProgressTrackerLogic)

    const verb =
        displayState === 'completed'
            ? 'completed'
            : displayState === 'error'
              ? 'error'
              : displayState === 'connecting'
                ? 'reconnecting'
                : 'running'
    const showElapsed = displayState === 'running' || displayState === 'completed'

    const completedCount = (latestSession?.tasks ?? []).filter((t) => t.status === 'completed').length
    const totalCount = latestSession?.tasks?.length ?? 0
    const progressPct = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0

    return (
        <>
            <div className="px-4 py-2.5 flex items-center justify-between gap-3 whitespace-nowrap">
                <div className="flex items-center gap-2.5 min-w-0">
                    <span aria-hidden className="inline-block w-2.5 h-2.5 bg-brand-red wizard-pulse-dot shrink-0" />
                    <span className="text-neutral-400 text-xs tracking-wider uppercase shrink-0">wizard</span>
                </div>
                <div className="flex items-baseline gap-2 shrink-0 text-neutral-100">
                    <span className="text-xs text-neutral-500 uppercase tracking-wider">{verb}</span>
                    {showElapsed ? (
                        <span className="font-semibold tabular-nums">{formatElapsed(elapsedSeconds)}</span>
                    ) : null}
                </div>
            </div>
            {totalCount > 0 ? (
                <div className="h-0.5 bg-neutral-900 relative">
                    <div
                        className="absolute inset-y-0 left-0 bg-brand-red transition-[width] duration-500"
                        style={{ width: `${progressPct}%` }}
                    />
                </div>
            ) : null}
            <style>{`
                @keyframes wizard-pulse-dot {
                    0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(245, 78, 0, 0.45); }
                    50% { opacity: 0.6; box-shadow: 0 0 0 4px rgba(245, 78, 0, 0); }
                }
                .wizard-pulse-dot { animation: wizard-pulse-dot 1.6s ease-in-out infinite; }
                @keyframes wizard-caret-blink {
                    0%, 50% { opacity: 1; }
                    50.01%, 100% { opacity: 0; }
                }
                .wizard-caret { animation: wizard-caret-blink 1s steps(1) infinite; }
                @keyframes wizard-task-row-glow {
                    0%, 100% { background-color: rgba(245, 78, 0, 0.06); }
                    50% { background-color: rgba(245, 78, 0, 0.12); }
                }
                .wizard-task-row-active { animation: wizard-task-row-glow 2s ease-in-out infinite; }
            `}</style>
        </>
    )
}

function StatusSubhead(): JSX.Element {
    const { latestSession, displayState } = useValues(wizardProgressTrackerLogic)
    if (!latestSession) {
        return <></>
    }

    return (
        <div className="px-4 py-2.5 border-t border-neutral-800/60 space-y-1">
            <div className="text-xs text-neutral-300">
                <Headline displayState={displayState} />{' '}
                <span className="text-neutral-500">
                    Detected: <span className="text-neutral-300">{latestSession.skill_id}</span>
                </span>
            </div>
            {displayState === 'running' || displayState === 'connecting' ? (
                <div className="text-[11px] text-neutral-500 leading-relaxed">
                    Usually 5–10 minutes — feel free to step away. Your code and credentials stay on your machine; we
                    cover the AI cost.
                </div>
            ) : null}
        </div>
    )
}

function Headline({ displayState }: { displayState: DisplayState }): JSX.Element {
    switch (displayState) {
        case 'completed':
            return <span className="text-neutral-100">PostHog is set up. You can keep going.</span>
        case 'error':
            return (
                <span className="text-neutral-100">The wizard couldn't finish. You can retry or set up manually.</span>
            )
        case 'connecting':
            return <span className="text-neutral-100">Reconnecting to the wizard…</span>
        default:
            return (
                <span className="text-neutral-100">The CLI is installing PostHog for you — no action needed here.</span>
            )
    }
}

function TaskList(): JSX.Element {
    const { latestSession, taskStartedAt, now } = useValues(wizardProgressTrackerLogic)
    const tasks = latestSession?.tasks ?? []

    if (tasks.length === 0) {
        return (
            <div className="text-neutral-400 flex items-center gap-2">
                <span className="text-brand-red inline-flex items-center">
                    <Spinner textColored speed="0.9s" />
                </span>
                <span>
                    analyzing project<span className="wizard-caret">_</span>
                </span>
            </div>
        )
    }

    return (
        <ul className="m-0 p-0 list-none -mx-2">
            {tasks.map((task) => {
                const isActive = task.status === 'in_progress'
                const startedAt = taskStartedAt[task.id]
                const taskElapsed = isActive && startedAt ? Math.max(0, Math.floor((now - startedAt) / 1000)) : null
                return (
                    <li
                        key={task.id}
                        className={`flex items-start gap-2 px-2 py-0.5 rounded ${
                            isActive ? 'wizard-task-row-active' : ''
                        }`}
                    >
                        <TaskIcon status={task.status} />
                        <span
                            className={
                                task.status === 'completed' || task.status === 'canceled'
                                    ? 'line-through text-neutral-500'
                                    : task.status === 'failed'
                                      ? 'text-brand-red'
                                      : 'text-neutral-100'
                            }
                        >
                            {task.title}
                        </span>
                        {isActive ? (
                            <span aria-hidden className="text-brand-red wizard-caret">
                                _
                            </span>
                        ) : null}
                        {taskElapsed !== null ? (
                            <span className="ml-auto text-[11px] text-neutral-500 tabular-nums shrink-0">
                                {formatShortElapsed(taskElapsed)}
                            </span>
                        ) : null}
                    </li>
                )
            })}
        </ul>
    )
}

function TaskIcon({ status }: { status: string }): JSX.Element {
    if (status === 'in_progress') {
        return (
            <span className="inline-flex items-center justify-center w-4 text-brand-red">
                <Spinner textColored speed="0.9s" />
            </span>
        )
    }
    const symbol = status === 'completed' ? '✓' : status === 'failed' ? '✗' : status === 'canceled' ? '⊘' : '☐'
    const color = status === 'completed' ? 'text-success' : status === 'failed' ? 'text-brand-red' : 'text-neutral-600'
    return <span className={`inline-block w-4 ${color}`}>{symbol}</span>
}

function ActivityLog(): JSX.Element {
    const { activityLog } = useValues(wizardProgressTrackerLogic)
    const recent: ActivityEntry[] = activityLog.slice(-8)
    return (
        <div className="text-xs leading-relaxed text-neutral-300">
            {recent.length === 0 ? (
                <div>
                    <span className="text-brand-red">&gt;</span> waiting<span className="wizard-caret">_</span>
                </div>
            ) : (
                recent.map((entry, i) => (
                    <div key={`${entry.at}-${i}`}>
                        <span className="text-brand-red">&gt;</span>{' '}
                        <span className="text-neutral-500">{formatTime(entry.at)}</span> {entry.text}
                        {i === recent.length - 1 ? <span className="wizard-caret">_</span> : null}
                    </div>
                ))
            )}
        </div>
    )
}

function Footer({ onManualSetup }: { onManualSetup?: () => void }): JSX.Element {
    const { latestSession, displayState } = useValues(wizardProgressTrackerLogic)
    const showManualLink =
        onManualSetup !== undefined &&
        (displayState === 'running' || displayState === 'connecting' || displayState === 'error')
    const errorPayload =
        displayState === 'error' && latestSession?.error && typeof latestSession.error === 'object'
            ? (latestSession.error as { type?: string; message?: string })
            : null

    const feedbackHref = `mailto:hey@posthog.com?subject=${encodeURIComponent('Onboarding wizard feedback')}`

    return (
        <div className="px-4 py-2.5 border-t border-neutral-800 text-xs flex items-center justify-between gap-3 flex-wrap">
            <div className="min-w-0 flex items-center gap-3 flex-wrap">
                {errorPayload ? (
                    <span className="text-brand-red min-w-0">
                        <span className="font-semibold">{errorPayload.type}: </span>
                        <span className="text-neutral-300">{errorPayload.message}</span>
                    </span>
                ) : null}
                {displayState === 'completed' ? (
                    <span className="text-neutral-400">
                        Hit <span className="text-neutral-200">Continue</span> below to finish onboarding.
                    </span>
                ) : null}
            </div>
            <div className="flex items-center gap-3 shrink-0">
                <Link
                    to={feedbackHref}
                    className="text-neutral-500 hover:text-neutral-300 transition-colors"
                    target="_blank"
                >
                    feedback?
                </Link>
                {showManualLink ? (
                    <button
                        type="button"
                        onClick={onManualSetup}
                        className="text-neutral-500 hover:text-neutral-300 transition-colors"
                    >
                        set up manually →
                    </button>
                ) : null}
            </div>
        </div>
    )
}

function CompletionRecap(): JSX.Element {
    const { latestSession } = useValues(wizardProgressTrackerLogic)
    const tasks = latestSession?.tasks ?? []
    const completed = tasks.filter((t) => t.status === 'completed')

    return (
        <div className="space-y-4">
            <div className="flex items-center gap-2 text-xs text-neutral-300">
                <span className="text-success">✓</span>
                <span>
                    {completed.length} {completed.length === 1 ? 'step' : 'steps'} installed —{' '}
                    <span className="text-neutral-500">your project is wired up.</span>
                </span>
            </div>
            <ul className="m-0 p-0 list-none grid grid-cols-1 sm:grid-cols-3 gap-2">
                {COMPLETION_LINKS.map((item) => (
                    <li key={item.title}>
                        <Link
                            to={item.href}
                            target="_blank"
                            className="block h-full rounded border border-neutral-800 hover:border-neutral-700 bg-neutral-900/60 hover:bg-neutral-900 transition-colors px-3 py-2.5"
                        >
                            <div className="text-xs text-neutral-100 font-semibold">{item.title}</div>
                            <div className="text-[11px] text-neutral-400 leading-snug mt-0.5">{item.blurb}</div>
                            <div className="text-[11px] text-brand-red mt-1.5">{item.cta} →</div>
                        </Link>
                    </li>
                ))}
            </ul>
            {completed.length > 0 ? (
                <details className="text-[11px] text-neutral-500">
                    <summary className="cursor-pointer hover:text-neutral-300 transition-colors select-none">
                        view setup details
                    </summary>
                    <ul className="m-0 mt-2 p-0 list-none space-y-0.5">
                        {completed.map((t) => (
                            <li key={t.id} className="flex items-start gap-2">
                                <span className="text-success shrink-0">✓</span>
                                <span className="line-through text-neutral-500">{t.title}</span>
                            </li>
                        ))}
                    </ul>
                </details>
            ) : null}
        </div>
    )
}

const COMPLETION_LINKS: Array<{ title: string; blurb: string; cta: string; href: string }> = [
    {
        title: 'See live events',
        blurb: 'Confirm PostHog is receiving from your app.',
        cta: 'open activity',
        href: 'https://posthog.com/docs/getting-started/install',
    },
    {
        title: 'Session replay',
        blurb: 'Watch real user sessions — every click and rage-tap.',
        cta: 'docs',
        href: 'https://posthog.com/docs/session-replay',
    },
    {
        title: 'Feature flags',
        blurb: 'Ship safely with targeted rollouts and A/B tests.',
        cta: 'docs',
        href: 'https://posthog.com/docs/feature-flags',
    },
]

function formatElapsed(seconds: number): string {
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m}:${s.toString().padStart(2, '0')}`
}

function formatShortElapsed(seconds: number): string {
    if (seconds < 60) {
        return `${seconds}s`
    }
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return s === 0 ? `${m}m` : `${m}m ${s}s`
}

function formatTime(epochMs: number): string {
    const d = new Date(epochMs)
    const pad = (n: number): string => n.toString().padStart(2, '0')
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}
