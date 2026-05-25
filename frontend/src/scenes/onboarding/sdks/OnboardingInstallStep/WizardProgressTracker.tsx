import { useValues } from 'kea'

import { type ActivityEntry, wizardProgressTrackerLogic } from './wizardProgressTrackerLogic'

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

    if (displayState === 'preTakeover') {
        return null
    }

    return (
        <div className="w-full font-mono text-sm bg-neutral-950 text-neutral-100 rounded-lg border border-neutral-800 shadow-2xl shadow-black/30 overflow-hidden">
            <TerminalHeader />
            <StatusSubhead />
            <div className="px-4 py-3 border-t border-neutral-800">
                <TaskList />
            </div>
            <div className="px-4 py-3 border-t border-neutral-800">
                <ActivityLog />
            </div>
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
                @keyframes wizard-task-active {
                    0%, 100% { opacity: 1; }
                    50% { opacity: 0.45; }
                }
                .wizard-task-active-icon { animation: wizard-task-active 1.2s ease-in-out infinite; }
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

    const headline =
        displayState === 'completed'
            ? "PostHog's wired into your project."
            : displayState === 'error'
              ? 'The wizard ran into trouble.'
              : displayState === 'connecting'
                ? 'Reconnecting to the wizard…'
                : "The wizard's installing PostHog for you."

    return (
        <div className="px-4 py-2 text-xs text-neutral-400 border-t border-neutral-800/60">
            {headline}{' '}
            <span className="text-neutral-500">
                Detected: <span className="text-neutral-300">{latestSession.skill_id}</span>
            </span>
        </div>
    )
}

function TaskList(): JSX.Element {
    const { latestSession } = useValues(wizardProgressTrackerLogic)
    const tasks = latestSession?.tasks ?? []

    if (tasks.length === 0) {
        return (
            <div className="text-neutral-400">
                <span aria-hidden className="text-brand-red">
                    ▶
                </span>{' '}
                analyzing project<span className="wizard-caret">_</span>
            </div>
        )
    }

    return (
        <ul className="m-0 p-0 list-none -mx-2">
            {tasks.map((task) => {
                const isActive = task.status === 'in_progress'
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
                    </li>
                )
            })}
        </ul>
    )
}

function TaskIcon({ status }: { status: string }): JSX.Element {
    const symbol =
        status === 'completed'
            ? '✓'
            : status === 'in_progress'
              ? '▶'
              : status === 'failed'
                ? '✗'
                : status === 'canceled'
                  ? '⊘'
                  : '☐'
    const color =
        status === 'completed'
            ? 'text-success'
            : status === 'failed'
              ? 'text-brand-red'
              : status === 'in_progress'
                ? 'text-brand-red'
                : 'text-neutral-600'
    const animation = status === 'in_progress' ? 'wizard-task-active-icon' : ''
    return <span className={`inline-block w-4 ${color} ${animation}`}>{symbol}</span>
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

    if (!showManualLink && !errorPayload) {
        return <></>
    }

    return (
        <div className="px-4 py-2.5 border-t border-neutral-800 text-xs flex items-center justify-between gap-3">
            {errorPayload ? (
                <div className="text-brand-red min-w-0">
                    <span className="font-semibold">{errorPayload.type}: </span>
                    <span className="text-neutral-300">{errorPayload.message}</span>
                </div>
            ) : (
                <span />
            )}
            {showManualLink ? (
                <button
                    type="button"
                    onClick={onManualSetup}
                    className="text-neutral-500 hover:text-neutral-300 transition-colors shrink-0"
                >
                    set up manually →
                </button>
            ) : null}
        </div>
    )
}

function formatElapsed(seconds: number): string {
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m}:${s.toString().padStart(2, '0')}`
}

function formatTime(epochMs: number): string {
    const d = new Date(epochMs)
    const pad = (n: number): string => n.toString().padStart(2, '0')
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}
