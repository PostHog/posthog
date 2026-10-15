import { useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { sessionRecordingSavedFiltersLogic } from '../filters/sessionRecordingSavedFiltersLogic'

export function SavedFiltersEmptyState(): JSX.Element {
    const { loadSavedFiltersFailed } = useValues(sessionRecordingSavedFiltersLogic)
    return loadSavedFiltersFailed ? (
        <LemonBanner type="error">Error while trying to load saved filters.</LemonBanner>
    ) : (
        <div className="flex items-center justify-center">
            <div className="max-w-248 mt-12 flex flex-col items-center">
                <h2 className="text-xl">You don't have any saved filters yet.</h2>
                <p className="text-secondary">
                    To create a saved filter, you need to have at least one filter applied.
                </p>
            </div>
        </div>
    )
}

export function SavedFiltersLoadingState(): JSX.Element {
    const { loadSavedFiltersFailed } = useValues(sessionRecordingSavedFiltersLogic)
    return loadSavedFiltersFailed ? (
        <LemonBanner type="error">Error while trying to load saved filters.</LemonBanner>
    ) : (
        <div className="space-y-2 p-4">
            <LemonSkeleton className="h-8 w-full" />
            <LemonSkeleton className="h-8 w-full" />
            <LemonSkeleton className="h-8 w-4/5" />
        </div>
    )
}
