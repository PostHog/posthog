import FireSaleBanner from 'scenes/data-warehouse/FireSaleBanner'
import { ViewLinkModal } from 'scenes/data-warehouse/ViewLinkModal'
import { DatabaseSearchField } from 'scenes/data-warehouse/editor/sidebar/DatabaseSearchField'
import { QueryDatabase } from 'scenes/data-warehouse/editor/sidebar/QueryDatabase'

import { PanelLayoutPanel } from '../PanelLayoutPanel'
import { SyncMoreNotice } from './SyncMoreNotice'

export function DatabaseTree(): JSX.Element {
    return (
        <PanelLayoutPanel searchField={<DatabaseSearchField placeholder="Search warehouse" />}>
            <FireSaleBanner />
            <QueryDatabase />
            <SyncMoreNotice />
            <ViewLinkModal />
        </PanelLayoutPanel>
    )
}
