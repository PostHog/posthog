import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { ViewLinkModal } from 'scenes/data-warehouse/ViewLinkModal'
import { DatabaseSearchField } from 'scenes/data-warehouse/editor/sidebar/DatabaseSearchField'
import { QueryDatabase } from 'scenes/data-warehouse/editor/sidebar/QueryDatabase'

import { SyncMoreNotice } from './SyncMoreNotice'

export function DatabaseTree(): JSX.Element {
    return (
        <ScrollableShadows
            direction="vertical"
            className="flex flex-col gap-2 z-20 border-r border-primary group/colorful-product-icons colorful-product-icons-true h-[calc(100vh-var(--scene-layout-header-height))] overflow-auto"
            innerClassName="p-3 flex flex-col gap-2"
            styledScrollbars
        >
            <DatabaseSearchField placeholder="Search warehouse" />
            <div className="-mx-2 grow">
                <QueryDatabase />
            </div>
            <SyncMoreNotice />
            <ViewLinkModal />
        </ScrollableShadows>
    )
}
