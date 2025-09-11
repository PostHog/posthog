import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

export function NotebookLoadingState(): JSX.Element {
    return (
        <div className="deprecated-space-y-4 px-8 py-4">
            <LemonSkeleton className="w-1/2 h-8" />
            <LemonSkeleton className="w-1/3 h-4" />
            <LemonSkeleton className="h-4" />
            <LemonSkeleton className="h-4" />
        </div>
    )
}
