import { IconBrackets, IconDatabase } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { clsx } from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { DatabaseTableTree, TreeItem } from 'lib/components/DatabaseTableTree/DatabaseTableTree'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { useState } from 'react'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { DatabaseSchemaTable } from '~/queries/schema'
import { ExternalDataSourceType, InsightLogicProps } from '~/types'

import { SOURCE_DETAILS } from '../new/sourceWizardLogic'
import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { dataWarehouseSceneLogic } from '../settings/dataWarehouseSceneLogic'
import { viewLinkLogic } from '../viewLinkLogic'
import { ViewLinkModal } from '../ViewLinkModal'
import { DeleteTableModal, TableData } from './TableData'

interface DataWarehousetTablesProps {
    insightProps: InsightLogicProps
}

export const DataWarehouseTables = ({ insightProps }: DataWarehousetTablesProps): JSX.Element => {
    const { query } = useValues(insightDataLogic(insightProps))
    const { setQuery: setInsightQuery } = useActions(insightDataLogic(insightProps))

    return (
        <>
            <BindLogic logic={insightLogic} props={insightProps}>
                <div className="Insight">
                    <Query
                        query={query}
                        setQuery={setInsightQuery}
                        readOnly={false}
                        context={{
                            showOpenEditorButton: false,
                            showQueryEditor: false,
                            showQueryHelp: false,
                            insightProps,
                        }}
                    />
                </div>
            </BindLogic>
        </>
    )
}

interface DatabaseTableTreeProps {
    inline?: boolean
}

export const DatabaseTableTreeWithItems = ({ inline }: DatabaseTableTreeProps): JSX.Element => {
    const { dataWarehouseTablesBySourceType, posthogTables, databaseLoading, views, selectedRow, schemaModalIsOpen } =
        useValues(dataWarehouseSceneLogic)
    const { selectRow, deleteDataWarehouseSavedQuery, deleteDataWarehouseTable, toggleSchemaModal } =
        useActions(dataWarehouseSceneLogic)
    const [collapsed, setCollapsed] = useState(false)
    const { toggleJoinTableModal, selectSourceTable } = useActions(viewLinkLogic)
    const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false)
    const { featureFlags } = useValues(featureFlagLogic)
    const { runDataWarehouseSavedQuery } = useActions(dataWarehouseViewsLogic)

    const deleteButton = (table: DatabaseSchemaTable | null): JSX.Element => {
        if (!table) {
            return <></>
        }

        if (table.type === 'view' || table.type === 'data_warehouse') {
            return (
                <LemonButton
                    data-attr="schema-list-item-delete"
                    status="danger"
                    onClick={() => {
                        selectRow(table)
                        setIsDeleteModalOpen(true)
                    }}
                    fullWidth
                >
                    Delete
                </LemonButton>
            )
        }

        if (table.type === 'posthog') {
            return <></>
        }

        return <></>
    }

    const dropdownOverlay = (table: DatabaseSchemaTable): JSX.Element => (
        <>
            <LemonButton
                onClick={() => {
                    void copyToClipboard(table.name, table.name)
                }}
                fullWidth
                data-attr="schema-list-item-copy"
            >
                Copy table name
            </LemonButton>
            <LemonButton
                onClick={() => {
                    selectRow(table)
                    toggleSchemaModal()
                }}
                data-attr="schema-list-item-schema"
                fullWidth
            >
                View table schema
            </LemonButton>
            <LemonButton
                onClick={() => {
                    selectSourceTable(table.name)
                    toggleJoinTableModal()
                }}
                data-attr="schema-list-item-join"
                fullWidth
            >
                Add join
            </LemonButton>
            {table.type == 'view' && (
                <LemonButton
                    onClick={() => {
                        router.actions.push(urls.dataWarehouseView(table.id))
                    }}
                    data-attr="schema-list-item-edit"
                    fullWidth
                >
                    Edit view definition
                </LemonButton>
            )}
            {table.type == 'view' && featureFlags[FEATURE_FLAGS.DATA_MODELING] && (
                <LemonButton
                    onClick={() => {
                        runDataWarehouseSavedQuery(table.id)
                    }}
                    data-attr="schema-list-item-materialize"
                    fullWidth
                >
                    Materialize
                </LemonButton>
            )}
            {deleteButton(table)}
        </>
    )

    const treeItems = (): TreeItem[] => {
        if (inline) {
            const items: TreeItem[] = [
                {
                    name: 'External',
                    items: Object.keys(dataWarehouseTablesBySourceType).map((source_type) => ({
                        name: SOURCE_DETAILS[source_type as ExternalDataSourceType]?.label ?? source_type,
                        items: dataWarehouseTablesBySourceType[source_type].map((table) => ({
                            name: table.name,
                            table: table,
                            dropdownOverlay: dropdownOverlay(table),
                            items: Object.values(table.fields).map((column) => ({
                                name: column.name,
                                type: column.type,
                                icon: <IconDatabase />,
                            })),
                        })),
                    })),
                    emptyLabel: <span className="text-muted">No tables found</span>,
                    isLoading: databaseLoading,
                },
                {
                    name: 'PostHog',
                    items: posthogTables.map((table) => ({
                        name: table.name,
                        table: table,
                        dropdownOverlay: dropdownOverlay(table),
                        items: Object.values(table.fields).map((column) => ({
                            name: column.name,
                            type: column.type,
                            icon: <IconDatabase />,
                        })),
                    })),
                    isLoading: databaseLoading,
                },
                {
                    name: 'Views',
                    items: views.map((table) => ({
                        name: table.name,
                        table: table,
                        dropdownOverlay: dropdownOverlay(table),
                        items: Object.values(table.fields).map((column) => ({
                            name: column.name,
                            type: column.type,
                            icon: <IconDatabase />,
                        })),
                    })),
                    emptyLabel: <span className="text-muted">No views found</span>,
                    isLoading: databaseLoading,
                },
            ]

            return items
        }

        const items: TreeItem[] = [
            {
                name: 'External',
                items: Object.keys(dataWarehouseTablesBySourceType).map((source_type) => ({
                    name: source_type,
                    items: dataWarehouseTablesBySourceType[source_type].map((table) => ({
                        table: table,
                        icon: <IconDatabase />,
                    })),
                })),
                emptyLabel: <span className="text-muted">No tables found</span>,
                isLoading: databaseLoading,
            },
            {
                name: 'PostHog',
                items: posthogTables.map((table) => ({
                    table: table,
                    icon: <IconDatabase />,
                })),
                isLoading: databaseLoading,
            },
            {
                name: 'Views',
                items: views.map((table) => ({
                    table: table,
                    icon: <IconBrackets />,
                })),
                emptyLabel: <span className="text-muted">No views found</span>,
                isLoading: databaseLoading,
            },
        ]

        return items
    }

    return (
        <div
            className={clsx(
                `bg-bg-light space-y-px rounded border p-2 overflow-y-auto`,
                !collapsed ? 'min-w-80 flex-1' : ''
            )}
        >
            {collapsed ? (
                <LemonButton icon={<IconDatabase />} onClick={() => setCollapsed(false)} />
            ) : (
                <>
                    <LemonButton
                        size="xsmall"
                        onClick={() => setCollapsed(true)}
                        fullWidth
                        icon={<IconDatabase />}
                        className="font-normal"
                    >
                        <span className="uppercase text-muted-alt tracking-wider">Sources</span>
                    </LemonButton>
                    <DatabaseTableTree onSelectRow={selectRow} items={treeItems()} selectedRow={selectedRow} />
                </>
            )}
            <LemonModal
                width="50rem"
                isOpen={!!selectedRow && schemaModalIsOpen}
                onClose={() => {
                    selectRow(null)
                    toggleSchemaModal()
                }}
                title="Table Schema"
            >
                <TableData />
            </LemonModal>
            <ViewLinkModal />
            {selectedRow && (
                <DeleteTableModal
                    table={selectedRow}
                    isOpen={isDeleteModalOpen}
                    setIsOpen={setIsDeleteModalOpen}
                    onDelete={() => {
                        if (selectedRow) {
                            if (selectedRow.type === 'view') {
                                deleteDataWarehouseSavedQuery(selectedRow.id)
                            } else {
                                deleteDataWarehouseTable(selectedRow.id)
                            }
                        }
                    }}
                />
            )}
        </div>
    )
}
