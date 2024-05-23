import { IconGear } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import { DataWarehouseTables } from './DataWarehouseTables'

export const scene: SceneExport = {
    component: DataWarehouseExternalScene,
    logic: dataWarehouseSceneLogic,
}

export function DataWarehouseExternalScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <div>
            <PageHeader
                buttons={
                    <>
                        {featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE] && (
                            <LemonButton
                                type="secondary"
                                data-attr="new-data-warehouse-view"
                                key="new-data-warehouse-view"
                                to={urls.insightNewHogQL('SELECT event AS event FROM events LIMIT 100')}
                            >
                                Create View
                            </LemonButton>
                        )}
                        <LemonButton
                            type="primary"
                            data-attr="new-data-warehouse-easy-link"
                            key="new-data-warehouse-easy-link"
                            to={urls.dataWarehouseTable()}
                        >
                            Link Source
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

            <DataWarehouseTables />
        </div>
    )
}
