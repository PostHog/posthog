import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { ViewLinkModal } from 'scenes/data-warehouse/ViewLinkModal'
import { DatabaseSearchField } from 'scenes/data-warehouse/editor/sidebar/DatabaseSearchField'
import { QueryDatabase } from 'scenes/data-warehouse/editor/sidebar/QueryDatabase'

import { SyncMoreNotice } from './SyncMoreNotice'

export function DatabaseTree(): JSX.Element {
    return (
        <div className="flex flex-col">
            <DatabaseSearchField placeholder="Search warehouse" />
            <ScrollableShadows
                direction="vertical"
                className="flex flex-col gap-2 z-20 border-r border-primary h-full group/colorful-product-icons colorful-product-icons-true grow overflow-auto"
                innerClassName="p-3"
            >
                <div className="-mx-2 grow">
                    <QueryDatabase />
                </div>
            </ScrollableShadows>
            <SyncMoreNotice />
            <ViewLinkModal />
        </div>
    )
}
