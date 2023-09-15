import { LemonButton, LemonTag } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { databaseSceneLogic } from 'scenes/data-management/database/databaseSceneLogic'
import { DataWarehousePageTabs, dataWarehouseTabsLogic } from '../DataWarehousePageTabs'
import { DatabaseTablesContainer } from 'scenes/data-management/database/DatabaseTables'
import { ViewLinkModal } from '../ViewLinkModal'
import { useActions, useValues } from 'kea'
import { viewLinkLogic } from '../viewLinkLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export const scene: SceneExport = {
    component: DataWarehousePosthogScene,
    logic: databaseSceneLogic,
}

export function DataWarehousePosthogScene(): JSX.Element {
    const { toggleFieldModal } = useActions(viewLinkLogic)
    const { tab } = useValues(dataWarehouseTabsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
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
                buttons={
                    featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_VIEWS] ? (
                        <LemonButton type="primary" data-attr="new-data-warehouse-table" onClick={toggleFieldModal}>
                            Link table to view
                        </LemonButton>
                    ) : undefined
                }
            />
            <DataWarehousePageTabs tab={tab} />
            <DatabaseTablesContainer />
            <ViewLinkModal tableSelectable={true} />
        </div>
    )
}
