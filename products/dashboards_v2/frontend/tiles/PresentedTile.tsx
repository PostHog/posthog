import './PresentedTile.css'

import { useEffect } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { Button, Dialog, DialogContent, DialogTitle } from '@posthog/quill'

import { type ContentWidget, type Tile, isSectionWidget } from '../dashboard/dashboardTypes'
import { useDashboardV2 } from '../dashboard/dashboardV2Context'
import { inReadingOrder } from '../grid/gridTiles'
import { WidgetCard } from './WidgetCard'

/** A tab's content tiles in the order a person reads them, the tiles in a section where the section sits. */
function contentTilesInOrder(tiles: Tile[]): { id: string; widget: ContentWidget }[] {
    return inReadingOrder(tiles).flatMap(({ id, widget }) =>
        isSectionWidget(widget) ? contentTilesInOrder(widget.tiles) : [{ id, widget }]
    )
}

export function PresentedTile(): JSX.Element {
    const { activeTab, widgets, presentedTileId, presentTile } = useDashboardV2()
    const tiles = contentTilesInOrder(activeTab.tiles)
    const index = tiles.findIndex((tile) => tile.id === presentedTileId)
    const widget = tiles[index]?.widget ?? null
    const previous = tiles[index - 1]?.id ?? null
    const next = tiles[index + 1]?.id ?? null

    useEffect(() => {
        if (!widget) {
            return
        }
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.key === 'ArrowLeft' && previous) {
                presentTile(previous)
            } else if (event.key === 'ArrowRight' && next) {
                presentTile(next)
            }
        }
        // Captured, because the focused tooltip trigger inside the card stops arrow keys from bubbling.
        window.addEventListener('keydown', onKeyDown, true)
        return () => window.removeEventListener('keydown', onKeyDown, true)
    }, [widget, previous, next, presentTile])

    return (
        <Dialog open={!!widget} onOpenChange={(open) => !open && presentTile(null)}>
            <DialogContent size="wide" className="PresentedTile" data-attr="dashboard-v2-presented-tile">
                <DialogTitle className="sr-only">{widget?.title || 'Tile'}</DialogTitle>
                {widget && <WidgetCard widget={widget} widgets={widgets} />}
                <Button
                    size="icon"
                    variant="outline"
                    className="PresentedTile__step PresentedTile__step--previous"
                    aria-label="Previous tile"
                    tooltip="Previous tile (←)"
                    aria-keyshortcuts="ArrowLeft"
                    data-attr="dashboard-v2-presented-tile-previous"
                    disabled={!previous}
                    onClick={() => previous && presentTile(previous)}
                >
                    <IconChevronLeft />
                </Button>
                <Button
                    size="icon"
                    variant="outline"
                    className="PresentedTile__step PresentedTile__step--next"
                    aria-label="Next tile"
                    tooltip="Next tile (→)"
                    aria-keyshortcuts="ArrowRight"
                    data-attr="dashboard-v2-presented-tile-next"
                    disabled={!next}
                    onClick={() => next && presentTile(next)}
                >
                    <IconChevronRight />
                </Button>
            </DialogContent>
        </Dialog>
    )
}
