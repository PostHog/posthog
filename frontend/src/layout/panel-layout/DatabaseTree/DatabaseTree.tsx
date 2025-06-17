import { DatabaseSearchField } from 'scenes/data-warehouse/editor/sidebar/DatabaseSearchField'
import { QueryDatabaseTreeView } from 'scenes/data-warehouse/editor/sidebar/QueryDatabase'

import { PanelLayoutPanel } from '../PanelLayoutPanel'

export function DatabaseTree(): JSX.Element {
    return (
        <PanelLayoutPanel searchField={<DatabaseSearchField placeholder="Search database" />}>
            <QueryDatabaseTreeView />
        </PanelLayoutPanel>
    )
}
