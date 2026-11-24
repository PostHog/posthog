import './ExpandedTile.css'

import { Dialog, DialogContent, DialogTitle } from '@posthog/quill'

import { isSectionWidget } from '../dashboard/dashboardTypes'
import { useDashboardV2 } from '../dashboard/dashboardV2Context'
import { findTile } from '../dashboard/tileTree'
import { WidgetCard } from './WidgetCard'

export function ExpandedTile(): JSX.Element {
    const { dashboard, widgets, expandedTileId, expandTile } = useDashboardV2()
    const tile = expandedTileId ? findTile(dashboard, expandedTileId) : null
    const widget = tile && !isSectionWidget(tile.widget) ? tile.widget : null
    return (
        <Dialog open={!!widget} onOpenChange={(open) => !open && expandTile(null)}>
            <DialogContent size="full" className="ExpandedTile" data-attr="dashboard-v2-expanded-tile">
                <DialogTitle className="sr-only">{widget?.title || 'Tile'}</DialogTitle>
                {widget && <WidgetCard widget={widget} widgets={widgets} />}
            </DialogContent>
        </Dialog>
    )
}
