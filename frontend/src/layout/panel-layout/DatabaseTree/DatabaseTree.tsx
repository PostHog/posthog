import { ViewLinkModal } from 'scenes/data-warehouse/ViewLinkModal'
import { DatabaseSearchField } from 'scenes/data-warehouse/editor/sidebar/DatabaseSearchField'
import { QueryDatabase } from 'scenes/data-warehouse/editor/sidebar/QueryDatabase'

import { SyncMoreNotice } from './SyncMoreNotice'

export function DatabaseTree(): JSX.Element {
    return (
        <div className="flex flex-col gap-2 p-3 z-20 border-r border-primary group/colorful-product-icons colorful-product-icons-true">
            <DatabaseSearchField placeholder="Search warehouse" />
            <div className="-mx-2 grow">
                <QueryDatabase />
            </div>
            <SyncMoreNotice />
            <ViewLinkModal />
        </div>
    )
}
