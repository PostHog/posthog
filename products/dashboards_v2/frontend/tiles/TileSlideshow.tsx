import './TileSlideshow.css'

import { useEffect } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { Button, Dialog, DialogContent, DialogTitle } from '@posthog/quill'

import { useDashboard } from '../dashboard/core/dashboardContext'
import { type Tile, isSectionPanel } from '../dashboard/document/dashboardTypes'
import { inReadingOrder } from '../grid/layout/gridTiles'
import { type SavedPanel } from '../panels/core/panelSchema'
import { ContentTile } from './core/ContentTile'

/** A tab's content tiles in the order a person reads them, the tiles in a section where the section sits. */
function contentTilesInOrder(tiles: Tile[]): { id: string; panel: SavedPanel }[] {
    return inReadingOrder(tiles).flatMap(({ id, panel }) =>
        isSectionPanel(panel) ? contentTilesInOrder(panel.tiles) : [{ id, panel }]
    )
}

export function TileSlideshow(): JSX.Element {
    const { activeTab, panels, slideshowTileId, showSlideshow } = useDashboard()
    const tiles = contentTilesInOrder(activeTab.tiles)
    const index = tiles.findIndex((tile) => tile.id === slideshowTileId)
    const panel = tiles[index]?.panel ?? null
    const previous = tiles[index - 1]?.id ?? null
    const next = tiles[index + 1]?.id ?? null

    useEffect(() => {
        if (!panel) {
            return
        }
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.key === 'ArrowLeft' && previous) {
                showSlideshow(previous)
            } else if (event.key === 'ArrowRight' && next) {
                showSlideshow(next)
            }
        }
        // TODO(2026-11-25): Use `useKeyboardHotkeys` once it can listen in the capture phase.
        // The focused tooltip trigger inside the card stops arrow keys from bubbling, so a bubble-phase listener such
        // as `useKeyboardHotkeys` never sees them.
        window.addEventListener('keydown', onKeyDown, true)
        return () => window.removeEventListener('keydown', onKeyDown, true)
    }, [panel, previous, next, showSlideshow])

    return (
        <Dialog open={!!panel} onOpenChange={(open) => !open && showSlideshow(null)}>
            <DialogContent size="wide" className="TileSlideshow" data-attr="dashboard-v2-tile-slideshow">
                <DialogTitle className="sr-only">{panel?.title || 'Tile'}</DialogTitle>
                {panel && <ContentTile panel={panel} panels={panels} />}
                <Button
                    size="icon"
                    variant="outline"
                    className="TileSlideshow__step TileSlideshow__step--previous"
                    aria-label="Previous tile"
                    tooltip="Previous tile (←)"
                    aria-keyshortcuts="ArrowLeft"
                    data-attr="dashboard-v2-tile-slideshow-previous"
                    disabled={!previous}
                    onClick={() => previous && showSlideshow(previous)}
                >
                    <IconChevronLeft />
                </Button>
                <Button
                    size="icon"
                    variant="outline"
                    className="TileSlideshow__step TileSlideshow__step--next"
                    aria-label="Next tile"
                    tooltip="Next tile (→)"
                    aria-keyshortcuts="ArrowRight"
                    data-attr="dashboard-v2-tile-slideshow-next"
                    disabled={!next}
                    onClick={() => next && showSlideshow(next)}
                >
                    <IconChevronRight />
                </Button>
            </DialogContent>
        </Dialog>
    )
}
