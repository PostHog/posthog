import { useActions, useValues } from 'kea'

import { IconSidePanel, IconSidebarClose } from '@posthog/icons'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'
import { ViewLinkModal } from 'scenes/data-warehouse/ViewLinkModal'
import { editorSizingLogic } from 'scenes/data-warehouse/editor/editorSizingLogic'
import { DatabaseSearchField } from 'scenes/data-warehouse/editor/sidebar/DatabaseSearchField'
import { QueryDatabase } from 'scenes/data-warehouse/editor/sidebar/QueryDatabase'

import { SyncMoreNotice } from './SyncMoreNotice'

export function DatabaseTree({ databaseTreeRef }: { databaseTreeRef: React.RefObject<HTMLDivElement> }): JSX.Element {
    const { databaseTreeWidth, databaseTreeResizerProps, isDatabaseTreeCollapsed } = useValues(editorSizingLogic)
    const { toggleDatabaseTreeCollapsed } = useActions(editorSizingLogic)

    return (
        <div
            className={cn(
                'relative bg-primary border-r border-primary',
                isDatabaseTreeCollapsed ? 'w-11' : `w-[var(--database-tree-width)]`
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    '--database-tree-width': `${databaseTreeWidth}px`,
                } as React.CSSProperties & { '--database-tree-width': string }
            }
            ref={databaseTreeRef}
        >
            <ScrollableShadows
                direction="vertical"
                className="flex flex-col gap-2 z-20 group/colorful-product-icons colorful-product-icons-true h-[calc(100vh-var(--scene-layout-header-height))] overflow-auto"
                innerClassName={cn('py-2 pl-2 pr-1 flex flex-col gap-2', !isDatabaseTreeCollapsed && 'pr-2')}
                styledScrollbars
            >
                <div className="flex items-center gap-1 w-full">
                    <ButtonPrimitive
                        onClick={toggleDatabaseTreeCollapsed}
                        tooltip={isDatabaseTreeCollapsed ? 'Expand database tree' : 'Collapse database tree'}
                        className="shrink-0 z-50 h-[32px]"
                        iconOnly
                    >
                        {isDatabaseTreeCollapsed ? (
                            <IconSidePanel className="size-4 text-tertiary" />
                        ) : (
                            <IconSidebarClose className="size-4 text-tertiary" />
                        )}
                    </ButtonPrimitive>
                    {!isDatabaseTreeCollapsed && <DatabaseSearchField placeholder="Search warehouse" />}
                </div>
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
            <Resizer {...databaseTreeResizerProps} />
        </div>
    )
}
