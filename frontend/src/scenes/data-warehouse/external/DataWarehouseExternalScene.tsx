import { LemonButton, Link } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { PipelineTab } from '~/types'

import { DataWarehouseInitialBillingLimitNotice } from '../DataWarehouseInitialBillingLimitNotice'
import { dataWarehouseExternalSceneLogic } from './dataWarehouseExternalSceneLogic'
import { DataWarehouseTables } from './DataWarehouseTables'

export const scene: SceneExport = {
    component: DataWarehouseExternalScene,
    logic: dataWarehouseExternalSceneLogic,
}

export function DataWarehouseExternalScene(): JSX.Element {
    const { insightSaving } = useValues(
        insightLogic({
            dashboardItemId: 'new-dataWarehouse',
            cachedInsight: null,
        })
    )
    const { saveAs } = useActions(
        insightLogic({
            dashboardItemId: 'new-dataWarehouse',
            cachedInsight: null,
        })
    )

    return (
        <div>
            <PageHeader
                buttons={
                    <>
                        <LemonButton
                            type="primary"
                            data-attr="save-exploration"
                            onClick={() => saveAs(true)}
                            loading={insightSaving}
                        >
                            Save as insight
                        </LemonButton>
                        <LemonButton type="secondary" to={urls.pipeline(PipelineTab.Sources)}>
                            Manage sources
                        </LemonButton>
                    </>
                }
                caption={
                    <div>
                        Explore all your data in PostHog with{' '}
                        <Link to="https://posthog.com/manual/hogql" target="_blank">
                            HogQL
                        </Link>
                        . Connect your own tables from S3 to query data from outside PostHog.{' '}
                        <Link to="https://posthog.com/docs/data/data-warehouse">Learn more</Link>
                    </div>
                }
            />
            <DataWarehouseInitialBillingLimitNotice />
            <BindLogic logic={insightSceneLogic} props={{}}>
                <DataWarehouseTables />
            </BindLogic>
        </div>
    )
}
