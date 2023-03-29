import { PageHeader } from 'lib/components/PageHeader'
import { DataManagementPageTabs, DataManagementTab } from 'scenes/data-management/DataManagementPageTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { databaseSceneLogic } from './databaseSceneLogic'
import { useActions, useValues } from 'kea'
import { LemonButton, LemonInput, LemonModal, LemonSegmentedButton } from '@posthog/lemon-ui'
import { DataBeachTableForm } from './DataBeachTableForm'
import { DatabaseTables } from 'scenes/data-management/database/DatabaseTables'

export function DatabaseScene(): JSX.Element {
    const { addingDataBeachTable, searchTerm } = useValues(databaseSceneLogic)
    const { showAddDataBeachTable, hideAddDataBeachTable, setSearchTerm } = useActions(databaseSceneLogic)

    return (
        <div data-attr="database-scene">
            <PageHeader
                title="Data Management"
                caption="Use data management to organize events that come into PostHog. Reduce noise, clarify usage, and help collaborators get the most value from your data."
                tabbedPage
            />
            <DataManagementPageTabs tab={DataManagementTab.Database} />
            <div className="flex items-center justify-between gap-2 mb-4">
                <LemonInput type="search" placeholder="Search for tables" onChange={setSearchTerm} value={searchTerm} />
                <LemonSegmentedButton
                    size={'small'}
                    onChange={() => {}}
                    value={''}
                    options={[
                        { label: 'All tables', value: '' },
                        { label: 'PostHog tables', value: 'posthog' },
                        { label: 'DataBeach tables', value: 'databeach' },
                    ]}
                />
            </div>
            <div className="flex items-center justify-between gap-2 mb-4">
                <div>
                    These are the database tables you can query under SQL insights with{' '}
                    <a href="https://posthog.com/manual/hogql" target="_blank">
                        HogQL
                    </a>
                    .
                </div>
                <LemonModal
                    title={'Add new DataBeach table'}
                    isOpen={addingDataBeachTable}
                    onClose={hideAddDataBeachTable}
                    width={560}
                >
                    <DataBeachTableForm dataBeachTable={null} onCancel={hideAddDataBeachTable} />
                </LemonModal>
                <LemonButton
                    type="secondary"
                    onClick={addingDataBeachTable ? hideAddDataBeachTable : showAddDataBeachTable}
                >
                    Add DataBeach table
                </LemonButton>
            </div>
            <DatabaseTables />
        </div>
    )
}

export const scene: SceneExport = {
    component: DatabaseScene,
    logic: databaseSceneLogic,
}
