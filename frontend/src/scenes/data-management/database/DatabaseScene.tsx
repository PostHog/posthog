import { PageHeader } from 'lib/components/PageHeader'
import { DataManagementPageTabs, DataManagementTab } from 'scenes/data-management/DataManagementPageTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { databaseSceneLogic } from './databaseSceneLogic'
import { useActions, useValues } from 'kea'
import { LemonInput, Link } from '@posthog/lemon-ui'
import { DatabaseTablesContainer } from 'scenes/data-management/database/DatabaseTables'

export function DatabaseScene(): JSX.Element {
    const { searchTerm } = useValues(databaseSceneLogic)
    const { setSearchTerm } = useActions(databaseSceneLogic)

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
            </div>
            <div className="flex items-center justify-between gap-2 mb-4">
                <div>
                    These are the database tables you can query under SQL insights with{' '}
                    <Link to="https://posthog.com/manual/hogql" target="_blank">
                        HogQL
                    </Link>
                    .
                </div>
            </div>
            <DatabaseTablesContainer />
        </div>
    )
}

export const scene: SceneExport = {
    component: DatabaseScene,
    logic: databaseSceneLogic,
}
