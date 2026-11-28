import './ContentTile.css'

import clsx from 'clsx'
import { type CSSProperties, useEffect, useMemo, useState } from 'react'

import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@posthog/quill'

import type { MenuAction } from '../../menu/menuAction'
import { ErrorBoundary, PANEL_ERROR_TAG } from '../../panels/core/ErrorBoundary'
import { type PanelType, panelSlots } from '../../panels/core/panelDefinition'
import { type SavedPanel, shownDescription } from '../../panels/core/panelSchema'
import { type TileCustomization, findPanel } from '../../panels/core/panelSpec'
import { PanelView } from '../../panels/core/PanelView'
import { TileBackgroundContext } from '../../panels/core/tileBackground'
import { DESCRIPTION_IMAGE_ONLY_CLASS, DescriptionIcon } from './DescriptionIcon'
import { TileActions } from './TileActions'
import { showsBorder, tileBackgroundColor, tileBackgroundStyle } from './tileAppearance'
import { TileContextMenu, hasTileMenu } from './TileContextMenu'
import { hasPart, isPartShown, showsPart } from './tileParts'

export const INTERACTIVE_ONLY_CLASS = 'dash-ContentTile--interactive-only'

const NO_ACTIONS: MenuAction[] = []

function cardLook(
    panel: SavedPanel,
    customizations: TileCustomization[],
    fromPanel: string | null
): { className: string; style: CSSProperties | undefined } {
    const color = fromPanel ?? tileBackgroundColor(panel, customizations)
    return {
        className: clsx(!showsBorder(panel) && 'dash-ContentTile--no-border'),
        style: tileBackgroundStyle(color),
    }
}

/**
 * One panel in its card: header, body and footer. It reads no dashboard, so a page can render a single panel on
 * its own. Inside a dashboard, `DashboardContentTile` passes both kinds of actions.
 */
function heightAnimates(): boolean {
    return (
        typeof CSS !== 'undefined' &&
        CSS.supports?.('interpolate-size', 'allow-keywords') === true &&
        !window.matchMedia('(prefers-reduced-motion: reduce)').matches
    )
}

export function ContentTile({
    panel,
    panels,
    actions = NO_ACTIONS,
    placementActions = NO_ACTIONS,
    editable = false,
    setConfig,
}: {
    panel: SavedPanel
    /** The panel types the page can show. The card renders the one that `panel.type` names. */
    panels: PanelType[]
    /** What a person can do to the tile itself, such as change its chart type. Shown on right-click. */
    actions?: MenuAction[]
    /** What a person can do to where the tile sits, such as move or remove it. Left out on a tile outside a dashboard. */
    placementActions?: MenuAction[]
    editable?: boolean
    /** Lets a panel that edits in place, such as text, save its config. Left out, the panel is read-only. */
    setConfig?: (config: unknown) => void
}): JSX.Element {
    const definition = findPanel(panels, panel.type)
    const slots = panelSlots(definition)
    const hasHeader = hasPart(panel, 'header', slots)
    const showHeader = hasHeader && showsPart(panel, 'header')
    // A hidden header unmounts once its animation ends, so a dashboard of headerless tiles carries no header markup.
    const [headerMounted, setHeaderMounted] = useState(showHeader)
    const [headerEntering, setHeaderEntering] = useState(false)
    if (showHeader && !headerMounted) {
        setHeaderMounted(true)
        setHeaderEntering(true)
    }
    // Without a height transition no transitionend fires, so the header unmounts straight away.
    useEffect(() => {
        if (!showHeader && headerMounted && !heightAnimates()) {
            setHeaderMounted(false)
            setHeaderEntering(false)
        }
    }, [showHeader, headerMounted])
    const showFooter = isPartShown(panel, 'footer', slots)
    const [backgroundFromPanel, setBackgroundFromPanel] = useState<string | null>(null)
    const look = cardLook(panel, definition?.allowedCustomizations ?? [], backgroundFromPanel)
    const { mode: descriptionMode, text: description } = shownDescription(panel)
    const HeaderExtra = definition?.HeaderExtra
    const Footer = definition?.Footer
    // Placement goes first so the slideshow stays above the image download in the shared view group.
    const menu = useMemo(() => [...placementActions, ...actions], [actions, placementActions])
    const hasMenu = hasTileMenu(menu)

    return (
        <TileContextMenu actions={menu}>
            <Card
                size="sm"
                // A tile without a header has no title bar, so the whole tile is what it is dragged by.
                className={clsx(
                    'dash-ContentTile',
                    look.className,
                    editable && !showHeader && 'TileGrid__handle',
                    definition?.showOnInteractiveOnly(panel) && INTERACTIVE_ONLY_CLASS
                )}
                style={look.style}
            >
                {hasHeader && (showHeader || headerMounted) && (
                    <CardHeader
                        className={clsx(
                            editable && showHeader && 'TileGrid__handle',
                            headerEntering && 'dash-ContentTile__header--entering',
                            !showHeader && 'dash-ContentTile__header--hidden'
                        )}
                        onTransitionEnd={(event) => {
                            if (
                                !showHeader &&
                                event.target === event.currentTarget &&
                                event.propertyName === 'height'
                            ) {
                                setHeaderMounted(false)
                                setHeaderEntering(false)
                            }
                        }}
                    >
                        <CardTitle className="flex items-center gap-1 min-w-0">
                            <span className="TileGrid__text truncate">{panel.title}</span>
                            {description && descriptionMode === 'icon' && <DescriptionIcon description={description} />}
                        </CardTitle>
                        {description && (
                            <CardDescription
                                className={clsx(
                                    'dash-ContentTile__description TileGrid__text',
                                    descriptionMode === 'icon' && DESCRIPTION_IMAGE_ONLY_CLASS
                                )}
                                title={description}
                            >
                                {description}
                            </CardDescription>
                        )}
                        {(HeaderExtra || hasMenu) && (
                            <TileActions menu={hasMenu}>
                                {HeaderExtra && (
                                    <ErrorBoundary resetKey={panel} tag={PANEL_ERROR_TAG} fallback={null}>
                                        <HeaderExtra panel={panel} />
                                    </ErrorBoundary>
                                )}
                            </TileActions>
                        )}
                    </CardHeader>
                )}
                {!showHeader && hasMenu && <TileActions menu className="dash-ContentTile__float-toolbar" />}
                <CardContent className="flex flex-col flex-1 min-h-0 overflow-hidden">
                    <TileBackgroundContext.Provider value={setBackgroundFromPanel}>
                        <PanelView panel={panel} definition={definition} setConfig={setConfig} />
                    </TileBackgroundContext.Provider>
                </CardContent>
                {showFooter && (
                    // The grid's drag cancel selector lists this class, so a tile dragged by its body never starts a drag here.
                    <CardFooter className="dash-ContentTile__footer flex shrink-0 items-center gap-2 min-w-0 text-xs text-secondary">
                        {Footer && (
                            <ErrorBoundary resetKey={panel} tag={PANEL_ERROR_TAG} fallback={null}>
                                <Footer panel={panel} />
                            </ErrorBoundary>
                        )}
                    </CardFooter>
                )}
            </Card>
        </TileContextMenu>
    )
}
