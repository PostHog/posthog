import { IconBrain } from '@posthog/icons'

import { SignalRun } from '../../types'
import { CardSkeleton } from '../cards/CardSkeleton'
import { SignalRunCard } from '../cards/SignalRunCard'

/**
 * Runs tab: a flat, chronological (newest-first) list of the project's scout and signals-pipeline
 * tasks. Each row links out to the standalone Tasks scene. `inboxSceneLogic` merges the two sources
 * and sorts them newest-first, so the tab renders the pre-sorted list as-is. A skeleton covers the
 * first load so the empty state doesn't flash before any data has been fetched.
 */
export function RunsTab({ runs, loading }: { runs: SignalRun[]; loading: boolean }): JSX.Element {
    return (
        <div className="mx-auto max-w-3xl flex flex-col gap-4 px-6 py-4">
            {loading ? (
                <CardSkeleton count={4} variant="cards" />
            ) : runs.length === 0 ? (
                <div className="mx-auto max-w-md flex flex-col items-center text-center py-16 gap-2">
                    <div className="flex items-center justify-center h-12 w-12 rounded-full bg-fill-primary text-secondary mb-1">
                        <IconBrain className="text-2xl" />
                    </div>
                    <h3 className="text-base font-semibold m-0">No runs yet</h3>
                    <p className="text-sm text-tertiary m-0">
                        Tasks kicked off by Self-driving – scouts exploring your project and the signals pipeline
                        researching reports – will show up here, newest first.
                    </p>
                </div>
            ) : (
                <div className="flex flex-col gap-3">
                    {runs.map((run) => (
                        <SignalRunCard key={run.task_id} run={run} />
                    ))}
                </div>
            )}
        </div>
    )
}
