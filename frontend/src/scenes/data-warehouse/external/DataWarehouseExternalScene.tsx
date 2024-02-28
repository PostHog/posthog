import { IconGear } from '@posthog/icons'
import { LemonButton, LemonTabs, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { DataWarehouseSceneTab } from '../types'
import { viewLinkLogic } from '../viewLinkLogic'
import { DataWarehouseJoins } from './DataWarehouseJoins'
import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import { DataWarehouseTables } from './DataWarehouseTables'

export const scene: SceneExport = {
    component: DataWarehouseExternalScene,
    logic: dataWarehouseSceneLogic,
}

const TABS_TO_CONTENT = {
    [DataWarehouseSceneTab.Tables]: {
        label: 'Tables',
        content: <DataWarehouseTables />,
    },
    [DataWarehouseSceneTab.Joins]: {
        label: 'Joins',
        content: <DataWarehouseJoins />,
    },
}

export function DataWarehouseExternalScene(): JSX.Element {
    const { activeSceneTab } = useValues(dataWarehouseSceneLogic)
    const { toggleSourceModal, setSceneTab } = useActions(dataWarehouseSceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { toggleNewJoinModal } = useActions(viewLinkLogic)

    const joinsEnabled = !!featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_JOINS]

    return (
        <div>
            <PageHeader
                buttons={
                    <>
                        {(activeSceneTab === DataWarehouseSceneTab.Tables || !joinsEnabled) && (
                            <>
                                {featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_VIEWS] && (
                                    <LemonButton
                                        type="primary"
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
                                    onClick={() => toggleSourceModal()}
                                >
                                    Link Source
                                </LemonButton>
                            </>
                        )}

                        {joinsEnabled && activeSceneTab === DataWarehouseSceneTab.Joins && (
                            <LemonButton
                                type="primary"
                                key="new-data-warehouse-join"
                                onClick={() => toggleNewJoinModal()}
                            >
                                Add Join
                            </LemonButton>
                        )}

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
            {joinsEnabled ? (
                <LemonTabs
                    activeKey={activeSceneTab}
                    onChange={(tab) => setSceneTab(tab as DataWarehouseSceneTab)}
                    tabs={Object.values(TABS_TO_CONTENT).map((tab, index) => ({
                        label: tab.label,
                        key: Object.keys(TABS_TO_CONTENT)[index],
                        content: tab.content,
                    }))}
                />
            ) : (
                <DataWarehouseTables />
            )}
        </div>
    )
}
