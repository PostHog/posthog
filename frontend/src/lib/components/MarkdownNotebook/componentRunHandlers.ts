import { createContext, useContext, useEffect } from 'react'

/** `disabledReason` mirrors the run button's own gate, so a shortcut can never start a run the
 * button would refuse. */
export type NotebookComponentRunHandler = {
    run: () => void
    disabledReason?: string | null
    isRunning?: boolean
    executionCount?: number | null
    interrupt?: () => void
}

// Lets the shell own the cell's key handling while knowing nothing about SQL or Python.
export const NotebookComponentRunHandlerContext = createContext<
    ((handler: NotebookComponentRunHandler | null) => void) | null
>(null)

export function usePublishNotebookComponentRunHandler(handler: NotebookComponentRunHandler | null): void {
    const publishRunHandler = useContext(NotebookComponentRunHandlerContext)
    const run = handler?.run
    const disabledReason = handler?.disabledReason ?? null
    const isRunning = handler?.isRunning ?? false
    const executionCount = handler?.executionCount ?? null
    const interrupt = handler?.interrupt

    useEffect(() => {
        if (!publishRunHandler) {
            return
        }

        publishRunHandler(run ? { run, disabledReason, isRunning, executionCount, interrupt } : null)

        return () => publishRunHandler(null)
    }, [publishRunHandler, run, disabledReason, isRunning, executionCount, interrupt])
}
