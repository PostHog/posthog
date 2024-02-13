import { TZLabel } from '@posthog/apps-common'
import { LemonButton, LemonDialog, LemonSwitch, LemonTable, LemonTag, Link, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { DataTableNode, NodeKind } from '~/queries/schema'
import { ExternalDataSourceSchema, ExternalDataStripeSource } from '~/types'

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

    const renderExpandable = (source: ExternalDataStripeSource): JSX.Element => {
        return (
            <div className="px-4 py-3">
                <div className="flex flex-col">
                    <div className="mt-2">
                        <SchemaTable schemas={source.schemas} />
                    </div>
                </div>
            </div>
        )
    }

    return (
        <div>
            <PageHeader
                buttons={
                    <LemonButton
                        type="primary"
                        data-attr="new-data-warehouse-easy-link"
                        key="new-data-warehouse-easy-link"
                        onClick={() => toggleSourceModal()}
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
                        key: 'frequency',
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
                expandable={{
                    expandedRowRender: renderExpandable,
                    rowExpandable: () => true,
                    noIndent: true,
                }}
            />
            <SourceModal isOpen={isSourceModalOpen} onClose={() => toggleSourceModal(false)} />
        </div>
    )
}

interface SchemaTableProps {
    schemas: ExternalDataSourceSchema[]
}

const SchemaTable = ({ schemas }: SchemaTableProps): JSX.Element => {
    const { updateSchema } = useActions(dataWarehouseSettingsLogic)

    return (
        <LemonTable
            dataSource={schemas}
            columns={[
                {
                    title: 'Schema Name',
                    key: 'name',
                    render: function RenderName(_, schema) {
                        return schema.name
                    },
                },
                {
                    title: 'Enabled',
                    key: 'should_sync',
                    render: function RenderShouldSync(_, schema) {
                        return (
                            <LemonSwitch
                                checked={schema.should_sync}
                                onChange={(active) => {
                                    updateSchema({ ...schema, should_sync: active })
                                }}
                            />
                        )
                    },
                },
                {
                    title: 'Synced Table',
                    key: 'table',
                    render: function RenderTable(_, schema) {
                        if (schema.table) {
                            const query: DataTableNode = {
                                kind: NodeKind.DataTableNode,
                                full: true,
                                source: {
                                    kind: NodeKind.HogQLQuery,
                                    // TODO: Use `hogql` tag?
                                    query: `SELECT ${schema.table.columns
                                        .filter(({ table, fields, chain }) => !table && !fields && !chain)
                                        .map(({ key }) => key)} FROM ${
                                        schema.table.name === 'numbers' ? 'numbers(0, 10)' : schema.table.name
                                    } LIMIT 100`,
                                },
                            }
                            return (
                                <Link to={urls.insightNew(undefined, undefined, JSON.stringify(query))}>
                                    <code>{schema.table.name}</code>
                                </Link>
                            )
                        } else {
                            return <div>Not yet synced</div>
                        }
                    },
                },
                {
                    title: 'Last Synced At',
                    key: 'last_synced_at',
                    render: function Render(_, schema) {
                        return schema.last_synced_at ? (
                            <>
                                <TZLabel time={schema.last_synced_at} formatDate="MMM DD, YYYY" formatTime="HH:mm" />
                            </>
                        ) : null
                    },
                },
            ]}
        />
    )
}
