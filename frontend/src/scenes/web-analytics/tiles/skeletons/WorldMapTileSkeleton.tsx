import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

export function WorldMapTileSkeleton(): JSX.Element {
    return (
        <div data-attr="web-analytics-skeleton-world-map" className="flex flex-col flex-1 px-4 py-4 gap-3">
            <LemonSkeleton className="w-full aspect-[2/1] rounded-md" />
            <div className="flex flex-row items-center justify-between">
                <LemonSkeleton className="h-3 w-24" />
                <LemonSkeleton className="h-3 w-32" />
            </div>
        </div>
    )
}
