import { IconDatabase, IconGear } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { DatabaseTableTree, TreeItem } from 'lib/components/DatabaseTableTree/DatabaseTableTree'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { PageHeader } from 'lib/components/PageHeader'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconDataObject } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DatabaseTable } from 'scenes/data-management/database/DatabaseTable'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema'

import { DataWarehouseRowType, DataWarehouseTableType } from '../types'
import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import SourceModal from './SourceModal'

export const scene: SceneExport = {
    component: DataWarehouseExternalScene,
    logic: dataWarehouseSceneLogic,
}

export function DataWarehouseExternalScene(): JSX.Element {
    const { isSourceModalOpen, externalTables, posthogTables, savedQueriesFormatted, allTables, selectedRow } =
        useValues(dataWarehouseSceneLogic)
    const { toggleSourceModal, selectRow, deleteDataWarehouseSavedQuery, deleteDataWarehouseTable } =
        useActions(dataWarehouseSceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const deleteButton = (selectedRow: DataWarehouseTableType | null): JSX.Element => {
        if (!selectedRow) {
            return <></>
        }

        if (selectedRow.type === DataWarehouseRowType.View) {
            return (
                <LemonButton
                    type="secondary"
                    onClick={() => {
                        deleteDataWarehouseSavedQuery(selectedRow.payload)
                    }}
                >
                    Delete
                </LemonButton>
            )
        }

        if (selectedRow.type === DataWarehouseRowType.ExternalTable) {
            return (
                <LemonButton
                    type="secondary"
                    onClick={() => {
                        deleteDataWarehouseTable(selectedRow.payload)
                    }}
                >
                    Delete
                </LemonButton>
            )
        }

        if (selectedRow.type === DataWarehouseRowType.PostHogTable) {
            return <></>
        }

        return <></>
    }

    const treeItems = (): TreeItem[] => {
        const items = [
            {
                name: 'External',
                items: externalTables.map((table) => ({
                    table: table,
                    icon: <IconDatabase />,
                })),
                emptyLabel: (
                    <span className="text-muted">
                        No tables found.{' '}
                        <Link
                            onClick={() => {
                                toggleSourceModal()
                            }}
                        >
                            Link source
                        </Link>
                    </span>
                ),
            },
            {
                name: 'PostHog',
                items: posthogTables.map((table) => ({
                    table: table,
                    icon: <IconDatabase />,
                })),
            },
        ]

        if (featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE]) {
            items.push({
                name: 'Views',
                items: savedQueriesFormatted.map((table) => ({
                    table: table,
                    icon: <IconDataObject />,
                })),
            })
        }

        return items
    }

    return (
        <div>
            <PageHeader
                buttons={
                    <>
                        {featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE] && (
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
            <div className="grid md:grid-cols-3">
                <div className="sm:col-span-3 md:col-span-1">
                    <DatabaseTableTree onSelectRow={selectRow} items={treeItems()} selectedRow={selectedRow} />
                </div>
                {selectedRow ? (
                    <div className="px-4 py-3 col-span-2">
                        <div className="flex flex-row justify-between items-center">
                            <h3>{selectedRow.name}</h3>
                            <div className="flex flex-row gap-2 justify-between">
                                {deleteButton(selectedRow)}
                                <Link
                                    to={urls.insightNew(
                                        undefined,
                                        undefined,
                                        JSON.stringify({
                                            kind: NodeKind.DataTableNode,
                                            full: true,
                                            source: {
                                                kind: NodeKind.HogQLQuery,
                                                // TODO: Use `hogql` tag?
                                                query: `SELECT ${selectedRow.columns
                                                    .filter(({ table, fields, chain }) => !table && !fields && !chain)
                                                    .map(({ key }) => key)} FROM ${selectedRow.name} LIMIT 100`,
                                            },
                                        })
                                    )}
                                >
                                    <LemonButton type="primary">Query</LemonButton>
                                </Link>
                            </div>
                        </div>
                        {selectedRow.type == DataWarehouseRowType.ExternalTable && (
                            <div className="flex flex-col">
                                <>
                                    <span className="card-secondary mt-2">Files URL pattern</span>
                                    <span>{selectedRow.payload.url_pattern}</span>
                                </>

                                <>
                                    <span className="card-secondary mt-2">File format</span>
                                    <span>{selectedRow.payload.format}</span>
                                </>
                            </div>
                        )}

                        <div className="mt-2">
                            <span className="card-secondary">Columns</span>
                            <DatabaseTable table={selectedRow.name} tables={allTables} />
                        </div>
                    </div>
                ) : (
                    <div className="px-4 py-3 h-100 col-span-2 flex justify-center items-center">
                        <EmptyMessage
                            title="No table selected"
                            description="Please select a table from the list on the left"
                            buttonText="Learn more about data warehouse tables"
                            buttonTo="https://posthog.com/docs/data-warehouse"
                        />
                    </div>
                )}
            </div>
            <SourceModal isOpen={isSourceModalOpen} onClose={() => toggleSourceModal(false)} />
        </div>
    )
}
