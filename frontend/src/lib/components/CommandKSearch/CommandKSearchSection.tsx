import { MenuLabel, Skeleton, cn } from '@posthog/quill'

import { CommandKSearchRow } from './CommandKSearchRow'
import { CommandKSection } from './commandKSections'

export function CommandKSearchSection({
    section,
    highlightedKey,
}: {
    section: CommandKSection
    highlightedKey: string | null
}): JSX.Element {
    return (
        <div
            role="group"
            aria-labelledby={`command-k-section-${section.key}`}
            data-attr={`command-k-section-${section.key}`}
        >
            <MenuLabel id={`command-k-section-${section.key}`} className="sticky top-0 z-10 bg-card px-2 pb-0">
                {section.label}
            </MenuLabel>
            <div
                className={cn(
                    'flex flex-col px-1 py-0.5 transition-opacity motion-reduce:transition-none',
                    // Dim only once a response is slow, so fast typing never flickers.
                    section.state === 'stale' && 'opacity-60 delay-150'
                )}
                aria-busy={section.state !== 'ready'}
            >
                {section.state === 'loading'
                    ? Array.from({ length: section.skeletonCount }, (_, index) => (
                          <div key={index} className="flex h-8 items-center px-1">
                              <Skeleton className="h-5 w-full" />
                          </div>
                      ))
                    : section.rows.map((row) => (
                          <CommandKSearchRow key={row.key} row={row} highlighted={row.key === highlightedKey} />
                      ))}
            </div>
        </div>
    )
}
