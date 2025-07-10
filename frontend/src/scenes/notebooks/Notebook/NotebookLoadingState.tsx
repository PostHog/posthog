import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

export function NotebookLoadingState(): JSX.Element {
    return (
        <div className="deprecated-space-y-4 px-8 py-4">
            <LemonSkeleton className="h-8 w-1/2" />
            <LemonSkeleton className="h-4 w-1/3" />
            <LemonSkeleton className="h-4" />
            <LemonSkeleton className="h-4" />
        </div>
    )
}
