import { Spinner } from 'lib/lemon-ui/Spinner'

import { TaskRow } from './TaskRow'

/**
 * Drops below the FAB header when the user expands the card. Surfaces a short
 * explainer plus the live task list with per-task elapsed time and simulated
 * progress bars.
 */
export function ExpandedDetails({
    tasks,
    taskStartedAt,
    now,
}: {
    tasks: Array<{ id: string; title: string; status: string }>
    taskStartedAt: Record<string, number>
    now: number
}): JSX.Element {
    return (
        <div className="border-t border-border px-3 py-3 space-y-3">
            <div className="text-xs text-muted">
                Close the tab or keep exploring — the wizard runs in the background and leaves a report when it&apos;s
                done.
            </div>
            {tasks.length === 0 ? (
                <div className="text-xs text-muted flex items-center gap-2">
                    <Spinner textColored speed="0.9s" />
                    <span>Analyzing your project…</span>
                </div>
            ) : (
                <ul className="m-0 p-0 list-none space-y-1.5">
                    {tasks.map((task) => (
                        <TaskRow key={task.id} task={task} startedAtMs={taskStartedAt[task.id]} nowMs={now} />
                    ))}
                </ul>
            )}
        </div>
    )
}
