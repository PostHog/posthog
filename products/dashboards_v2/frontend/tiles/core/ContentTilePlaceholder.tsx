import clsx from 'clsx'

import { Card, CardContent, CardHeader, CardTitle } from '@posthog/quill'

import { type PanelType, panelSlots } from '../../panels/core/panelDefinition'
import { PanelErrorBoundary } from '../../panels/core/PanelErrorBoundary'
import { type SavedPanel } from '../../panels/core/panelSchema'
import { PanelLoading } from '../../panels/core/PanelView'
import { INTERACTIVE_ONLY_CLASS } from './ContentTile'
import { isPartShown } from './tileParts'

/**
 * What a tile shows before its card mounts: the card's header and the panel type's loading state, so a tile that
 * scrolls into view already looks like itself. It reads no dashboard state, so off-screen tiles stay cheap.
 */
export function ContentTilePlaceholder({
    panel,
    definition,
    editable,
}: {
    panel: SavedPanel
    definition: PanelType | undefined
    editable: boolean
}): JSX.Element {
    const showHeader = isPartShown(panel, 'header', panelSlots(definition))
    const Loading = definition?.Loading ?? PanelLoading
    return (
        <Card
            size="sm"
            className={clsx(
                'dash-ContentTile',
                editable && !showHeader && 'TileGrid__handle',
                definition?.showOnInteractiveOnly(panel) && INTERACTIVE_ONLY_CLASS
            )}
            aria-busy
        >
            {showHeader && (
                <CardHeader className={clsx(editable && 'TileGrid__handle')}>
                    <CardTitle className="TileGrid__text truncate">{panel.title}</CardTitle>
                </CardHeader>
            )}
            <CardContent className="flex flex-col flex-1 min-h-0 overflow-hidden">
                <PanelErrorBoundary panel={panel} fallback={<PanelLoading />}>
                    <Loading panel={panel} />
                </PanelErrorBoundary>
            </CardContent>
        </Card>
    )
}
