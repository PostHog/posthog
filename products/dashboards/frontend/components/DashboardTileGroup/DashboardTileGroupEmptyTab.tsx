import * as peekOverPng from '@posthog/brand/hoggies/png/peek-over'
import { Button } from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'

const HedgehogPeekOver = pngHoggie(peekOverPng)

interface DashboardTileGroupEmptyTabProps {
    addAction?: React.ReactNode
    onRemove?: () => void
}

export function DashboardTileGroupEmptyTab({ addAction, onRemove }: DashboardTileGroupEmptyTabProps): JSX.Element {
    return (
        <div
            className="flex flex-col items-center gap-1 rounded-lg border border-dashed px-4 py-10 text-center"
            data-attr="dashboard-tile-group-empty-tab"
        >
            {/* The PNG is a square with the hedgehog in its middle, so crop to the drawing (x 180-820, y 300-700 of 1000). */}
            <div className="relative mb-3 aspect-[1.6] w-30 overflow-hidden">
                <HedgehogPeekOver
                    style={{ position: 'absolute', width: '156.25%', maxWidth: 'none', left: '-28.125%', top: '-75%' }}
                />
            </div>
            <h3 className="mb-0 text-base font-semibold">Nothing to see here yet</h3>
            <p className="mb-0 max-w-120 text-secondary">
                Add a new tile, or move one here from another tab with its Move to option.
            </p>
            {(addAction || onRemove) && (
                <div className="mt-3 flex flex-wrap justify-center gap-2">
                    {addAction}
                    {onRemove && (
                        <Button
                            variant="destructive-outline"
                            onClick={onRemove}
                            data-attr="dashboard-tile-group-empty-tab-remove"
                        >
                            Delete tab
                        </Button>
                    )}
                </div>
            )}
        </div>
    )
}
