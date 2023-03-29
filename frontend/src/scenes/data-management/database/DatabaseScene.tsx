import { PageHeader } from 'lib/components/PageHeader'
import { DataManagementPageTabs, DataManagementTab } from 'scenes/data-management/DataManagementPageTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { databaseSceneLogic } from './databaseSceneLogic'
import { useActions, useValues } from 'kea'
import { LemonTable } from 'lib/lemon-ui/LemonTable/LemonTable'
import { LemonButton, LemonInput, LemonModal, LemonSegmentedButton } from '@posthog/lemon-ui'
import { DataBeachTableForm } from './DataBeachTableForm'
import { DatabaseTable } from './DatabaseTable'
import { IconChevronRight } from 'lib/lemon-ui/icons'

export function DatabaseScene(): JSX.Element {
    const { database, addingDataBeachTable, searchTerm, expandedTables } = useValues(databaseSceneLogic)
    const { showAddDataBeachTable, hideAddDataBeachTable, setSearchTerm, toggleExpandedTable } =
        useActions(databaseSceneLogic)
    const tables = database ? Object.keys(database) : []

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
                    These are the database tables you can query in PostHog with{' '}
                    <a href="https://posthog.com/manual/hogql" target="_blank">
                        HogQL
                    </a>{' '}
                    under SQL insights.
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

            {tables.length === 0 ? <LemonTable loading={true} dataSource={[]} columns={[]} /> : null}

            {tables.map((table) => (
                <div key={table} className="mt-8">
                    <div className="flex">
                        <LemonButton onClick={() => toggleExpandedTable(table)} icon={<IconChevronRight />} />
                        Table: {table}
                    </div>
                    {expandedTables[table] ? <DatabaseTable database={database} table={table} /> : null}
                </div>
            ))}
        </div>
    )
}

export const scene: SceneExport = {
    component: DatabaseScene,
    logic: databaseSceneLogic,
}
