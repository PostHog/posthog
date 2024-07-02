import { IconBrackets, IconChevronDown, IconDatabase, IconGear } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { clsx } from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { DatabaseTableTree, TreeItem } from 'lib/components/DatabaseTableTree/DatabaseTableTree'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useState } from 'react'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { DatabaseSchemaTable } from '~/queries/schema'

import { viewLinkLogic } from '../viewLinkLogic'
import { ViewLinkModal } from '../ViewLinkModal'
import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import { DeleteTableModal, TableData } from './TableData'

export const DataWarehouseTables = (): JSX.Element => {
    // insightLogic
    const logic = insightLogic({
        dashboardItemId: 'new',
        cachedInsight: null,
    })
    const { insightProps } = useValues(logic)
    // insightDataLogic
    const { query } = useValues(
        insightDataLogic({
            ...insightProps,
        })
    )

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
    const { featureFlags } = useValues(featureFlagLogic)
    const [collapsed, setCollapsed] = useState(false)
    const { toggleJoinTableModal, selectSourceTable } = useActions(viewLinkLogic)
    const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false)

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
            {deleteButton(table)}
        </>
    )

    const treeItems = (): TreeItem[] => {
        if (inline) {
            const items: TreeItem[] = [
                {
                    name: 'External',
                    items: Object.keys(dataWarehouseTablesBySourceType).map((source_type) => ({
                        name: source_type,
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
            ]

            if (featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE]) {
                items.push({
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
                })
            }

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
        ]

        if (featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE]) {
            items.push({
                name: 'Views',
                items: views.map((table) => ({
                    table: table,
                    icon: <IconBrackets />,
                })),
                emptyLabel: <span className="text-muted">No views found</span>,
                isLoading: databaseLoading,
            })
        }

        return items
    }

    return (
        <div
            className={clsx(
                `bg-bg-light space-y-px rounded border p-2 overflow-y-auto max-h-screen`,
                !collapsed ? 'min-w-80 flex-1' : 'flex-0'
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
                        sideIcon={
                            <div className="flex flex-row gap-1">
                                <LemonButton
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        router.actions.push(urls.dataWarehouseTable())
                                    }}
                                    type="primary"
                                    size="xsmall"
                                >
                                    Link source
                                </LemonButton>
                                <LemonButton
                                    size="xsmall"
                                    type="primary"
                                    icon={<IconGear />}
                                    data-attr="new-data-warehouse-settings-link"
                                    key="new-data-warehouse-settings-link"
                                    onClick={() => router.actions.push(urls.dataWarehouseSettings())}
                                />
                                <IconChevronDown className="rotate-90 text-xl" />
                            </div>
                        }
                    >
                        <span className="uppercase text-muted-alt tracking-wider">Schemas</span>
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
