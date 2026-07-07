import { simulatedTaskFraction } from './helpers'
import { TaskStatusIcon } from './TaskStatusIcon'

/**
 * Single row in the FAB's expanded task list — status icon + title + per-task
 * elapsed seconds and a simulated progress bar for `in_progress` rows.
 *
 * The progress bar uses {@link simulatedTaskFraction} so it's always moving
 * between backend updates without ever claiming "done" on its own.
 */
export function TaskRow({
    task,
    startedAtMs,
    nowMs,
}: {
    task: { id: string; title: string; status: string }
    startedAtMs: number | undefined
    nowMs: number
}): JSX.Element {
    const isActive = task.status === 'in_progress'
    const elapsedS = isActive && startedAtMs ? Math.max(0, Math.floor((nowMs - startedAtMs) / 1000)) : null
    const titleClass =
        task.status === 'completed' || task.status === 'canceled'
            ? 'line-through text-muted'
            : task.status === 'failed'
              ? 'text-brand-red'
              : 'text-default'

    const simPct = isActive ? Math.round(simulatedTaskFraction(startedAtMs, nowMs) * 100) : 0

    return (
        <li className="flex items-start gap-2 text-xs">
            <span className="mt-0.5">
                <TaskStatusIcon status={task.status} />
            </span>
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                    <span className={`flex-1 min-w-0 truncate ${titleClass}`}>{task.title}</span>
                    {elapsedS !== null ? (
                        <span className="text-[10px] text-muted tabular-nums shrink-0">{elapsedS}s</span>
                    ) : null}
                </div>
                {isActive ? (
                    <div className="h-0.5 bg-bg-3000 mt-1 relative overflow-hidden rounded-full">
                        <div
                            className="absolute inset-y-0 left-0 bg-brand-red transition-[width] duration-1000 ease-out"
                            style={{ width: `${simPct}%` }}
                        />
                    </div>
                ) : null}
            </div>
        </li>
    )
}
