import { PageHeader } from 'lib/components/PageHeader'
import { DataManagementPageTabs, DataManagementTab } from 'scenes/data-management/DataManagementPageTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { databaseSceneLogic } from './databaseSceneLogic'
import { useActions, useValues } from 'kea'
import { LemonButton, LemonInput, LemonModal, LemonSegmentedButton } from '@posthog/lemon-ui'
import { DataBeachTableForm } from './DataBeachTableForm'
import { DatabaseTables } from 'scenes/data-management/database/DatabaseTables'

export function DatabaseScene(): JSX.Element {
    const { editingDataBeachTable, editingDataBeachTableObject, searchTerm, category } = useValues(databaseSceneLogic)
    const {
        editDataBeachTable,
        hideEditDataBeachTable,
        setSearchTerm,
        appendDataBeachTable,
        updateDataBeachTable,
        setCategory,
    } = useActions(databaseSceneLogic)

    return (
        <div data-attr="database-scene">
            <PageHeader
                title="Data Management"
                caption="Use data management to organize events that come into PostHog. Reduce noise, clarify usage, and help collaborators get the most value from your data."
                tabbedPage
            />
            <DataManagementPageTabs tab={DataManagementTab.Database} />
            <div className="flex items-center justify-between gap-2 mb-4">
                <div className="flex items-center justify-between gap-2">
                    <LemonInput
                        type="search"
                        placeholder="Search for tables"
                        onChange={setSearchTerm}
                        value={searchTerm}
                    />
                    <LemonSegmentedButton
                        size={'medium'}
                        onChange={setCategory}
                        value={category}
                        options={[
                            { label: 'All tables', value: 'all' },
                            { label: 'PostHog', value: 'posthog' },
                            { label: 'DataBeach', value: 'databeach' },
                        ]}
                    />
                </div>
                <LemonButton type="primary" onClick={() => editDataBeachTable('new')}>
                    New DataBeach table
                </LemonButton>
            </div>
            <div className="flex items-center justify-between gap-2 mb-4">
                <div>
                    These are the database tables you can query under SQL insights with{' '}
                    <a href="https://posthog.com/manual/hogql" target="_blank">
                        HogQL
                    </a>
                    .
                </div>
            </div>
            <DatabaseTables />
            <LemonModal
                title={editingDataBeachTable === 'new' ? 'Add new DataBeach table' : 'Edit DataBeach table'}
                isOpen={!!editingDataBeachTable}
                onClose={hideEditDataBeachTable}
                width={560}
            >
                <DataBeachTableForm
                    dataBeachTable={editingDataBeachTableObject ?? null}
                    onCancel={hideEditDataBeachTable}
                    onSave={(table) => {
                        if (editingDataBeachTable === 'new') {
                            appendDataBeachTable(table)
                        } else {
                            updateDataBeachTable(table)
                        }
                        hideEditDataBeachTable()
                    }}
                />
            </LemonModal>
        </div>
    )
}

export const scene: SceneExport = {
    component: DatabaseScene,
    logic: databaseSceneLogic,
}
