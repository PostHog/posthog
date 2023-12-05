import { TZLabel } from '@posthog/apps-common'
import { LemonButton, LemonDialog, LemonTable, LemonTag, Spinner } from '@posthog/lemon-ui'
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
    Running: 'primary',
    Completed: 'success',
    Error: 'danger',
    Failed: 'danger',
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
                        render: function RenderName(_, source) {
                            return source.source_type
                        },
                    },
                    {
                        title: 'Table Prefix',
                        key: 'prefix',
                        render: function RenderPrefix(_, source) {
                            return source.prefix
                        },
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        render: function RenderStatus(_, source) {
                            return (
                                <LemonTag type={StatusTagSetting[source.status] || 'default'}>{source.status}</LemonTag>
                            )
                        },
                    },
                    {
                        title: 'Sync Frequency',
                        key: 'prefix',
                        render: function RenderFrequency() {
                            return 'Every 24 hours'
                        },
                    },
                    {
                        title: 'Last Successful Run',
                        key: 'last_run_at',
                        tooltip: 'Time of the last run that completed a data import',
                        render: (_, run) => {
                            return run.last_run_at ? (
                                <TZLabel time={run.last_run_at} formatDate="MMM DD, YYYY" formatTime="HH:mm" />
                            ) : (
                                'Never'
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
                                                                LemonDialog.open({
                                                                    title: 'Delete data source?',
                                                                    description:
                                                                        'Are you sure you want to delete this data source? All related tables will be deleted.',

                                                                    primaryButton: {
                                                                        children: 'Delete',
                                                                        status: 'danger',
                                                                        onClick: () => deleteSource(source),
                                                                    },
                                                                    secondaryButton: {
                                                                        children: 'Cancel',
                                                                    },
                                                                })
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
            <SourceModal isOpen={isSourceModalOpen} onClose={() => toggleSourceModal(false)} />
        </div>
    )
}
