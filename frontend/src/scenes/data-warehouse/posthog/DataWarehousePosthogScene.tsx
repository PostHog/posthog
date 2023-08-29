import { LemonTag } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { databaseSceneLogic } from 'scenes/data-management/database/databaseSceneLogic'
import { DataWarehousePageTabs, DataWarehouseTab } from '../DataWarehousePageTabs'
import { DatabaseTablesContainer } from 'scenes/data-management/database/DatabaseTables'

export const scene: SceneExport = {
    component: DataWarehousePosthogScene,
    logic: databaseSceneLogic,
}

export function DataWarehousePosthogScene(): JSX.Element {
    return (
        <div>
            <PageHeader
                title={
                    <div className="flex items-center gap-2">
                        Data Warehouse
                        <LemonTag type="warning" className="uppercase">
                            Beta
                        </LemonTag>
                    </div>
                }
                caption={
                    <div>
                        These are the database tables you can query under SQL insights with{' '}
                        <a href="https://posthog.com/manual/hogql" target="_blank">
                            HogQL
                        </a>
                        .
                    </div>
                }
            />
            <DataWarehousePageTabs tab={DataWarehouseTab.Posthog} />
            <DatabaseTablesContainer />
        </div>
    )
}
