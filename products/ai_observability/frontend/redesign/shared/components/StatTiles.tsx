import { ReactNode } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

export interface StatTile {
    label: string
    /** Null while loading. */
    value: ReactNode | null
    tone?: 'danger' | 'default'
}

export interface StatTilesProps {
    tiles: StatTile[]
}

export function StatTiles({ tiles }: StatTilesProps): JSX.Element {
    return (
        <dl className="grid grid-cols-[repeat(auto-fill,minmax(8rem,1fr))] gap-2">
            {tiles.map((tile) => (
                <div key={tile.label} className="flex flex-col gap-1 rounded border border-primary px-3 py-2">
                    <dt className="text-xs text-secondary">{tile.label}</dt>
                    <dd
                        className={`m-0 text-base font-semibold tabular-nums ${tile.tone === 'danger' ? 'text-danger' : ''}`}
                    >
                        {tile.value === null ? <LemonSkeleton className="h-5 w-16" /> : tile.value}
                    </dd>
                </div>
            ))}
        </dl>
    )
}
