import { LemonButton, LemonTable, LemonTag, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { FEATURE_FLAGS } from 'lib/constants'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { dataWarehouseSceneLogic } from '../external/dataWarehouseSceneLogic'
import SourceModal from '../external/SourceModal'
import { dataWarehouseSettingsLogic } from './dataWarehouseSettingsLogic'

export const scene: SceneExport = {
    component: DataWarehouseSettingsScene,
    logic: dataWarehouseSettingsLogic,
}

const StatusTagSetting = {
    running: 'default',
    succeeded: 'primary',
    error: 'danger',
}

export function DataWarehouseSettingsScene(): JSX.Element {
    const { dataWarehouseSources, dataWarehouseSourcesLoading, sourceReloadingById } =
        useValues(dataWarehouseSettingsLogic)
    const { deleteSource, reloadSource } = useActions(dataWarehouseSettingsLogic)
    const { toggleSourceModal } = useActions(dataWarehouseSceneLogic)
    const { isSourceModalOpen } = useValues(dataWarehouseSceneLogic)
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
                buttons={
                    featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_EXTERNAL_LINK] ? (
                        <LemonButton
                            type="primary"
                            data-attr="new-data-warehouse-easy-link"
                            key={'new-data-warehouse-easy-link'}
                            onClick={() => toggleSourceModal()}
                        >
                            Link Source
                        </LemonButton>
                    ) : undefined
                }
                caption={
                    <div>
                        Linked data sources will appear here. Data sources can take a while to sync depending on the
                        size of the source.
                    </div>
                }
            />
            <LemonTable
                dataSource={dataWarehouseSources?.results ?? []}
                loading={dataWarehouseSourcesLoading}
                columns={[
                    {
                        title: 'Source Type',
                        key: 'name',
                        width: 0,
                        render: function RenderName(_, source) {
                            return source.source_type
                        },
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        width: 0,
                        render: function RenderStatus(_, source) {
                            return (
                                <LemonTag type={StatusTagSetting[source.status] || 'default'}>{source.status}</LemonTag>
                            )
                        },
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: function RenderActions(_, source) {
                            return (
                                <div className="flex flex-row justify-end">
                                    {sourceReloadingById[source.id] ? (
                                        <div>
                                            <Spinner />
                                        </div>
                                    ) : (
                                        <div>
                                            <More
                                                overlay={
                                                    <>
                                                        <LemonButton
                                                            type="tertiary"
                                                            data-attr={`reload-data-warehouse-${source.source_type}`}
                                                            key={`reload-data-warehouse-${source.source_type}`}
                                                            onClick={() => {
                                                                reloadSource(source)
                                                            }}
                                                        >
                                                            Reload
                                                        </LemonButton>
                                                        <LemonButton
                                                            status="danger"
                                                            data-attr={`delete-data-warehouse-${source.source_type}`}
                                                            key={`delete-data-warehouse-${source.source_type}`}
                                                            onClick={() => {
                                                                deleteSource(source)
                                                            }}
                                                        >
                                                            Delete
                                                        </LemonButton>
                                                    </>
                                                }
                                            />
                                        </div>
                                    )}
                                </div>
                            )
                        },
                    },
                ]}
            />
            <SourceModal isOpen={isSourceModalOpen} onClose={toggleSourceModal} />
        </div>
    )
}
