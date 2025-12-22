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
}): JSX.Element {
    const { databaseTreeWidth, databaseTreeResizerProps, isDatabaseTreeCollapsed, databaseTreeWillCollapse } =
        useValues(editorSizingLogic)
    const { toggleDatabaseTreeCollapsed, setDatabaseTreeCollapsed } = useActions(editorSizingLogic)

    return (
        <div
            className={cn(
                'relative bg-primary border-r border-primary transition-opacity duration-100 flex flex-col',
                isDatabaseTreeCollapsed ? 'w-11' : `w-[var(--database-tree-width)]`,
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
            <div className={cn('flex items-center gap-1 w-full p-2 pr-1', !isDatabaseTreeCollapsed && 'pr-2')}>
                <ButtonPrimitive
                    onClick={toggleDatabaseTreeCollapsed}
                    tooltip={isDatabaseTreeCollapsed ? 'Expand panel' : 'Collapse panel'}
                    className="shrink-0 z-50 h-[32px]"
                    iconOnly
                >
                    <IconSidebarClose
                        className={cn('size-4 text-tertiary rotate-180', isDatabaseTreeCollapsed && 'rotate-0')}
                    />
                </ButtonPrimitive>
                {!isDatabaseTreeCollapsed && <DatabaseSearchField placeholder="Search warehouse" />}
            </div>
            <ScrollableShadows
                direction="vertical"
                className="flex flex-col gap-2 z-20 group/colorful-product-icons colorful-product-icons-true h-[calc(100vh-var(--scene-layout-header-height))] overflow-auto"
                innerClassName="flex flex-col gap-2"
                styledScrollbars
            >
                {!isDatabaseTreeCollapsed && (
                    <>
                        <div className="grow w-full">
                            <QueryDatabase />
                        </div>
                        <SyncMoreNotice />
                        <ViewLinkModal />
                    </>
                )}
            </ScrollableShadows>
            <Resizer
                {...databaseTreeResizerProps}
                closeThreshold={DATABASE_TREE_COLLAPSE_THRESHOLD}
                onToggleClosed={(closed) => setDatabaseTreeCollapsed(closed)}
            />
        </div>
    )
})
