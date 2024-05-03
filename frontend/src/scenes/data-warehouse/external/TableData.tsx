import { LemonButton, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { useEffect, useState } from 'react'
import { DatabaseTable } from 'scenes/data-management/database/DatabaseTable'
import { urls } from 'scenes/urls'

import { HogQLQueryEditor } from '~/queries/nodes/HogQLQuery/HogQLQueryEditor'
import { HogQLQuery, NodeKind } from '~/queries/schema'
import { DataWarehouseSavedQuery } from '~/types'

import { DataWarehouseRowType, DataWarehouseTableType } from '../types'
import { viewLinkLogic } from '../viewLinkLogic'
import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'

export function TableData(): JSX.Element {
    const {
        selectedRow: table,
        isEditingSavedQuery,
        dataWarehouseSavedQueriesLoading,
        inEditSchemaMode,
        editSchemaIsLoading,
    } = useValues(dataWarehouseSceneLogic)
    const {
        deleteDataWarehouseSavedQuery,
        deleteDataWarehouseTable,
        setIsEditingSavedQuery,
        updateDataWarehouseSavedQuery,
        toggleEditSchemaMode,
        updateSelectedSchema,
        saveSchema,
        cancelEditSchema,
    } = useActions(dataWarehouseSceneLogic)
    const { toggleJoinTableModal, selectSourceTable } = useActions(viewLinkLogic)
    const [localQuery, setLocalQuery] = useState<HogQLQuery>()

    const isExternalTable = table?.type === DataWarehouseRowType.ExternalTable
    const isManuallyLinkedTable = isExternalTable && !table.payload.external_data_source

    useEffect(() => {
        if (table && 'query' in table.payload) {
            setLocalQuery(table.payload.query)
        }
    }, [table])

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

    return table ? (
        <div className="px-4 py-3 col-span-2">
            <div className="flex flex-row justify-between items-center gap-2">
                <h3 className="text-wrap break-all leading-4">{table.name}</h3>
                {isEditingSavedQuery && (
                    <div className="flex flex-row gap-2 justify-between">
                        <LemonButton type="secondary" onClick={() => setIsEditingSavedQuery(false)}>
                            Cancel
                        </LemonButton>
                    </div>
                )}
                {inEditSchemaMode && (
                    <div className="flex flex-row gap-2 justify-between">
                        <LemonButton
                            type="primary"
                            loading={editSchemaIsLoading}
                            onClick={() => {
                                saveSchema()
                            }}
                        >
                            Save schema
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            disabledReason={editSchemaIsLoading && 'Schema is saving...'}
                            onClick={() => {
                                cancelEditSchema()
                            }}
                        >
                            Cancel edit
                        </LemonButton>
                    </div>
                )}
                {!inEditSchemaMode && !isEditingSavedQuery && (
                    <div className="flex flex-row gap-2 justify-between">
                        {deleteButton(table)}
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                selectSourceTable(table.name)
                                toggleJoinTableModal()
                            }}
                        >
                            Add join
                        </LemonButton>
                        {isManuallyLinkedTable && (
                            <LemonButton
                                type="primary"
                                onClick={() => {
                                    toggleEditSchemaMode()
                                }}
                            >
                                Edit schema
                            </LemonButton>
                        )}
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
                                        query: `SELECT ${table.columns
                                            .filter(({ table, fields, chain }) => !table && !fields && !chain)
                                            .map(({ key }) => key)} FROM ${table.name} LIMIT 100`,
                                    },
                                })
                            )}
                        >
                            <LemonButton type="primary">Query</LemonButton>
                        </Link>
                        {'query' in table.payload && (
                            <LemonButton type="primary" onClick={() => setIsEditingSavedQuery(true)}>
                                Edit
                            </LemonButton>
                        )}
                    </div>
                )}
            </div>
            {table.type == DataWarehouseRowType.ExternalTable && (
                <div className="flex flex-col">
                    {table.payload.external_data_source && (
                        <>
                            <span className="card-secondary mt-2">Last Synced At</span>
                            <span>
                                {table.payload.external_schema?.last_synced_at
                                    ? humanFriendlyDetailedTime(
                                          table.payload.external_schema?.last_synced_at,
                                          'MMMM DD, YYYY',
                                          'h:mm A'
                                      )
                                    : 'Not yet synced'}
                            </span>
                        </>
                    )}

                    {!table.payload.external_data_source && (
                        <>
                            <span className="card-secondary mt-2">Files URL pattern</span>
                            <span className="break-all>{table.payload.url_pattern}</span>

                            <span className="card-secondary mt-2">File format</span>
                            <span>{table.payload.format}</span>
                        </>
                    )}
                </div>
            )}

            {!isEditingSavedQuery && (
                <div className="mt-2">
                    <span className="card-secondary">Columns</span>
                    <DatabaseTable
                        table={table.name}
                        tables={[table]}
                        inEditSchemaMode={inEditSchemaMode}
                        schemaOnChange={(key, type) => updateSelectedSchema(key, type)}
                    />
                </div>
            )}

            {'query' in table.payload && isEditingSavedQuery && (
                <div className="mt-2">
                    <span className="card-secondary">Update View Definition</span>
                    <HogQLQueryEditor
                        query={{
                            kind: NodeKind.HogQLQuery,
                            // TODO: Use `hogql` tag?
                            query: `${localQuery && localQuery.query}`,
                        }}
                        onChange={(queryInput) => {
                            setLocalQuery({
                                kind: NodeKind.HogQLQuery,
                                query: queryInput,
                            })
                        }}
                        editorFooter={(hasErrors, error, isValidView) => (
                            <LemonButton
                                className="ml-2"
                                onClick={() => {
                                    localQuery &&
                                        updateDataWarehouseSavedQuery({
                                            ...(table.payload as DataWarehouseSavedQuery),
                                            query: localQuery,
                                        })
                                }}
                                loading={dataWarehouseSavedQueriesLoading}
                                type="primary"
                                center
                                disabledReason={
                                    hasErrors
                                        ? error ?? 'Query has errors'
                                        : !isValidView
                                        ? 'All fields must have an alias'
                                        : ''
                                }
                                data-attr="hogql-query-editor-save-as-view"
                            >
                                Save as View
                            </LemonButton>
                        )}
                    />
                </div>
            )}
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
    )
}
