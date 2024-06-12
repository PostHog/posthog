import { IconGear } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { BindLogic } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { DataWarehouseBetaNotice } from '../DataWarehouseBetaNotice'
import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import { DataWarehouseTables } from './DataWarehouseTables'

export const scene: SceneExport = {
    component: DataWarehouseExternalScene,
    logic: dataWarehouseSceneLogic,
}

export function DataWarehouseExternalScene(): JSX.Element {
    return (
        <div>
            <PageHeader
                buttons={
                    <>
                        <LemonButton
                            type="primary"
                            data-attr="new-data-warehouse-easy-link"
                            key="new-data-warehouse-easy-link"
                            to={urls.dataWarehouseTable()}
                        >
                            Link source
                        </LemonButton>

                        <LemonButton
                            type="primary"
                            icon={<IconGear />}
                            data-attr="new-data-warehouse-settings-link"
                            key="new-data-warehouse-settings-link"
                            onClick={() => router.actions.push(urls.dataWarehouseSettings())}
                        />
                    </>
                }
                caption={
                    <div>
                        Below are all the sources that can be queried within PostHog with{' '}
                        <Link to="https://posthog.com/manual/hogql" target="_blank">
                            HogQL
                        </Link>
                        . Connect your own tables from S3 to query data from outside PostHog.{' '}
                        <Link to="https://posthog.com/docs/data/data-warehouse">Learn more</Link>
                    </div>
                }
            />
            <DataWarehouseBetaNotice />
            <BindLogic logic={insightSceneLogic} props={{}}>
                <DataWarehouseTables />
            </BindLogic>
        </div>
    )
}
