import { LemonButton } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { DataWarehousePricingNotice } from '../DataWarehousePricingNotice'
import { dataWarehouseSettingsLogic } from './dataWarehouseSettingsLogic'
import { DataWarehouseSourcesTable } from './DataWarehouseSourcesTable'

export const scene: SceneExport = {
    component: DataWarehouseSettingsScene,
    logic: dataWarehouseSettingsLogic,
}

export function DataWarehouseSettingsScene(): JSX.Element {
    return (
        <div>
            <PageHeader
                buttons={
                    <LemonButton
                        type="primary"
                        data-attr="new-data-warehouse-easy-link"
                        key="new-data-warehouse-easy-link"
                        to={urls.dataWarehouseTable()}
                    >
                        Link Source
                    </LemonButton>
                }
                caption={
                    <div>
                        Linked data sources will appear here. Data sources can take a while to sync depending on the
                        size of the source.
                    </div>
                }
            />
            <DataWarehousePricingNotice />
            <DataWarehouseSourcesTable />
        </div>
    )
}
