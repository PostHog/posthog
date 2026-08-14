import { useMountedLogic, useValues } from 'kea'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { notebookNodeGenUIActivityLogic } from './notebookNodeGenUIActivityLogic'

export interface GenUIGenerationActivityProps {
    taskId: string
}

export function GenUIGenerationActivity({ taskId }: GenUIGenerationActivityProps): JSX.Element {
    const logic = useMountedLogic(notebookNodeGenUIActivityLogic({ taskId }))
    const { activityItems, taskRunError, taskRunLoading } = useValues(logic)

    return (
        <div className="ml-5 mt-2 border-l-2 border-border pl-3 text-left text-xs" aria-live="off">
            <div className="mb-1 font-medium text-muted">Agent activity</div>
            {taskRunError ? <div className="text-muted">{taskRunError}</div> : null}
            {!taskRunError && activityItems.length === 0 ? (
                <div className="flex items-center gap-1.5 text-muted">
                    {taskRunLoading ? <Spinner className="shrink-0 text-xs" /> : null}
                    <span>
                        {taskRunLoading ? 'Connecting to agent activity' : "Waiting for the agent's first update"}
                    </span>
                </div>
            ) : null}
            {activityItems.length > 0 ? (
                <ol className="m-0 flex list-none flex-col gap-0.5 p-0">
                    {activityItems.map((item) => (
                        <li key={item.id} className="flex min-w-0 items-center gap-1.5 text-secondary">
                            {item.active ? (
                                <Spinner className="shrink-0 text-xs" />
                            ) : (
                                <span className="size-1.5 shrink-0 rounded-full bg-border-bold" />
                            )}
                            <span className="line-clamp-2 min-w-0 break-words">{item.text}</span>
                        </li>
                    ))}
                </ol>
            ) : null}
        </div>
    )
}
