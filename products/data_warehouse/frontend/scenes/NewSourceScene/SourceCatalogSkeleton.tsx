import { LemonSkeleton } from '@posthog/lemon-ui'

import { CATALOG_GRID_CLASS, CATALOG_TILE_CLASS } from './SourceCatalog'

// Roughly a screenful at a typical scene width, so the grid reads as a catalog mid-load rather
// than a handful of stray boxes. The real catalog is far longer, so there is nothing to match.
const PLACEHOLDER_TILE_COUNT = 12
const PLACEHOLDER_CATEGORY_COUNT = 8

/** Stands in for `SourceCatalog` while the connector list loads. */
export function SourceCatalogSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col sm:flex-row gap-4">
            <div className="flex flex-row sm:flex-col gap-1 sm:w-56 sm:shrink-0">
                <LemonSkeleton className="h-8" repeat={PLACEHOLDER_CATEGORY_COUNT} />
            </div>
            <div className="flex flex-col gap-4 flex-1">
                <LemonSkeleton className="h-10" />
                <div className={CATALOG_GRID_CLASS}>
                    {Array.from({ length: PLACEHOLDER_TILE_COUNT }, (_, index) => (
                        <div key={index} className={CATALOG_TILE_CLASS}>
                            {/* The catalog renders a medium SourceIcon, which is 60px square. */}
                            <LemonSkeleton className="size-[60px] shrink-0" />
                            <div className="flex flex-col gap-2 flex-1 min-w-0">
                                <LemonSkeleton className="h-4 w-3/4" />
                                <LemonSkeleton className="h-4 w-1/3" />
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    )
}
