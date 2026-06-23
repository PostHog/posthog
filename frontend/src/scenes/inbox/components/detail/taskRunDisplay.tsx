import clsx from 'clsx'

import { TaskRunStatus } from 'products/tasks/frontend/types'

import { SignalReportTaskRelationship } from '../../types'

/** Human label for a report→task relationship, shown next to a run in the inbox. */
export const RELATIONSHIP_LABEL: Record<SignalReportTaskRelationship, string> = {
    research: 'Research',
    implementation: 'Implementation',
    repo_selection: 'Repo selection',
}

/** Run statuses that count as terminal. Mirrors desktop `isTerminalStatus`. */
export const TERMINAL_STATUSES: TaskRunStatus[] = [
    TaskRunStatus.COMPLETED,
    TaskRunStatus.FAILED,
    TaskRunStatus.CANCELLED,
]

/** Small status dot: red for failed/cancelled, green for completed, pulsing blue while in motion. */
export function TaskRunStatusDot({ status }: { status: TaskRunStatus }): JSX.Element {
    const terminal = TERMINAL_STATUSES.includes(status)
    const color =
        status === TaskRunStatus.FAILED || status === TaskRunStatus.CANCELLED
            ? 'bg-danger'
            : terminal
              ? 'bg-success'
              : 'bg-primary'
    return (
        <span
            className={clsx('inline-block size-1.5 shrink-0 rounded-full', color, !terminal && 'animate-pulse')}
            aria-hidden
        />
    )
}
