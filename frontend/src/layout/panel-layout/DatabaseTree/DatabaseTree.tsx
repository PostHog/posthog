import { useActions, useValues } from 'kea'
import { memo } from 'react'

import { IconSidebarClose } from '@posthog/icons'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'
import { ViewLinkModal } from 'scenes/data-warehouse/ViewLinkModal'
import { DATABASE_TREE_COLLAPSE_THRESHOLD, editorSizingLogic } from 'scenes/data-warehouse/editor/editorSizingLogic'
import { DatabaseSearchField } from 'scenes/data-warehouse/editor/sidebar/DatabaseSearchField'
import { QueryDatabase } from 'scenes/data-warehouse/editor/sidebar/QueryDatabase'

import { SyncMoreNotice } from './SyncMoreNotice'

export const DatabaseTree = memo(function DatabaseTree({
    databaseTreeRef,
}: {
    databaseTreeRef: React.RefObject<HTMLDivElement>
}): JSX.Element | null {
    const { databaseTreeWidth, databaseTreeResizerProps, isDatabaseTreeCollapsed, databaseTreeWillCollapse } =
        useValues(editorSizingLogic)
    const { toggleDatabaseTreeCollapsed, setDatabaseTreeCollapsed } = useActions(editorSizingLogic)

    if (isDatabaseTreeCollapsed) {
        return null
    }

    return (
        <div
            className={cn(
                'relative bg-primary border-primary transition-opacity duration-100 flex flex-col',
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
            <div className="flex items-center gap-1 w-full p-2 pr-2">
                <ButtonPrimitive
                    onClick={toggleDatabaseTreeCollapsed}
                    tooltip="Collapse panel"
                    className="shrink-0 z-50 h-[32px]"
                    iconOnly
                >
                    <IconSidebarClose className="size-4 text-tertiary rotate-180" />
                </ButtonPrimitive>
                <DatabaseSearchField placeholder="Search warehouse" />
            </div>
            <ScrollableShadows
                direction="vertical"
                className="flex flex-col gap-2 z-20 group/colorful-product-icons colorful-product-icons-true h-[calc(100vh-var(--scene-layout-header-height))] overflow-auto"
                innerClassName="flex flex-col gap-2"
                styledScrollbars
            >
                <div className="grow w-full">
                    <QueryDatabase />
                </div>
                <SyncMoreNotice />
                <ViewLinkModal />
            </ScrollableShadows>
            <Resizer
                {...databaseTreeResizerProps}
                closeThreshold={DATABASE_TREE_COLLAPSE_THRESHOLD}
                onToggleClosed={(closed) => setDatabaseTreeCollapsed(closed)}
            />
        </div>
    )
})
