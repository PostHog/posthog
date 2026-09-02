import { useActions, useValues } from 'kea'
import { memo, useRef } from 'react'

import { IconSidebarClose } from '@posthog/icons'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'
import { ConnectionSelector } from 'scenes/data-warehouse/editor/ConnectionSelector'
import { DATABASE_TREE_COLLAPSE_THRESHOLD, editorSizingLogic } from 'scenes/data-warehouse/editor/editorSizingLogic'
import { DatabaseSearchField } from 'scenes/data-warehouse/editor/sidebar/DatabaseSearchField'
import { QueryDatabase } from 'scenes/data-warehouse/editor/sidebar/QueryDatabase'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { ExpressionModal } from 'scenes/data-warehouse/ExpressionModal'
import { ViewLinkModal } from 'scenes/data-warehouse/ViewLinkModal'

import { SyncMoreNotice } from './SyncMoreNotice'

export const DatabaseTree = memo(function DatabaseTree({
    databaseTreeRef,
    tabId,
    extraTreeSections,
    embedded = false,
}: {
    databaseTreeRef: React.RefObject<HTMLDivElement>
    tabId: string
    /** Extra top-level tree sections owned by the embedding surface — see QueryDatabase. */
    extraTreeSections?: TreeDataItem[]
    /** Rendered inside a notebook cell rather than the editor scene. */
    embedded?: boolean
}): JSX.Element | null {
    const scrollContainerRef = useRef<HTMLDivElement | null>(null)
    const {
        databaseTreeWidth,
        databaseTreeResizerProps,
        isDatabaseTreeCollapsed,
        databaseTreeWillCollapse,
        queryPaneDesiredSize,
    } = useValues(editorSizingLogic)
    const { selectedConnectionId, selectedDirectSource } = useValues(sqlEditorLogic({ tabId }))
    const { toggleDatabaseTreeCollapsed, setDatabaseTreeCollapsed } = useActions(editorSizingLogic)

    const searchPlaceholder = selectedConnectionId
        ? `Search ${selectedDirectSource?.prefix ? selectedDirectSource.prefix : 'database'}`
        : 'Search PostHog Warehouse'

    if (isDatabaseTreeCollapsed) {
        return null
    }

    return (
        <div
            className={cn(
                'relative bg-primary border-primary transition-opacity duration-100 flex flex-col shrink-0 w-[var(--database-tree-width)]',
                databaseTreeWillCollapse && 'opacity-50'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    '--database-tree-width': `${databaseTreeWidth}px`,
                } as React.CSSProperties & { '--database-tree-width': string }
            }
            ref={databaseTreeRef}
        >
            <div className="flex flex-col gap-2 w-full p-2 pr-2">
                <div className="flex items-center gap-1 w-full">
                    <ButtonPrimitive
                        onClick={toggleDatabaseTreeCollapsed}
                        tooltip="Collapse panel"
                        className="shrink-0 z-50 h-[32px]"
                        iconOnly
                    >
                        <IconSidebarClose className="size-4 text-tertiary rotate-180" />
                    </ButtonPrimitive>
                    <ConnectionSelector tabId={tabId} />
                </div>
                <DatabaseSearchField placeholder={searchPlaceholder} />
            </div>
            <ScrollableShadows
                scrollRef={scrollContainerRef}
                direction="vertical"
                className={cn(
                    'flex flex-col gap-2 z-20 group/colorful-product-icons colorful-product-icons-true overflow-auto',
                    // A notebook cell sizes to its content and has no viewport-tall box to fill, so a
                    // viewport-height panel drags the whole cell open. `h-0` keeps the schema list out of
                    // that height, leaving the editor pane to size the cell, and `flex-auto` takes whatever
                    // height the row lands on, with the list scrolling inside it.
                    embedded && 'h-0 flex-auto',
                    // Until the pane has been resized the cell would open at editor height, leaving the
                    // browser a sliver — so hold a floor. Once the user drags, drop it: their size wins,
                    // in both directions, and closing the browser returns the cell to where it was.
                    embedded && (queryPaneDesiredSize === null ? 'min-h-[200px]' : 'min-h-0'),
                    !embedded && 'h-[calc(100vh-var(--scene-layout-header-height))]'
                )}
                innerClassName="flex flex-col gap-2"
                styledScrollbars
            >
                <div className="grow w-full">
                    <QueryDatabase
                        virtualizationScrollContainerRef={scrollContainerRef}
                        extraTreeSections={extraTreeSections}
                        tabId={tabId}
                    />
                </div>
                <SyncMoreNotice />
                <ViewLinkModal />
                <ExpressionModal />
            </ScrollableShadows>
            <Resizer
                {...databaseTreeResizerProps}
                closeThreshold={DATABASE_TREE_COLLAPSE_THRESHOLD}
                onToggleClosed={(closed) => setDatabaseTreeCollapsed(closed)}
            />
        </div>
    )
})
