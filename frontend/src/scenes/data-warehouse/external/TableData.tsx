import { IconDatabase } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'kea-forms'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { Dispatch, SetStateAction } from 'react'
import { DatabaseTable } from 'scenes/data-management/database/DatabaseTable'

import { DatabaseSchemaTable } from '~/queries/schema'

import { dataWarehouseSceneLogic } from '../settings/dataWarehouseSceneLogic'

export function TableData(): JSX.Element {
    const {
        selectedRow: table,
        isEditingSavedQuery,
        inEditSchemaMode,
        editSchemaIsLoading,
    } = useValues(dataWarehouseSceneLogic)
    const { setIsEditingSavedQuery, toggleEditSchemaMode, updateSelectedSchema, saveSchema, cancelEditSchema } =
        useActions(dataWarehouseSceneLogic)

    const isExternalTable = table?.type === 'data_warehouse'
    const isManuallyLinkedTable = isExternalTable && !table.source

    return (
        <div className="border rounded p-3 bg-bg-light">
            {table ? (
                <>
                    <div className="flex flex-row justify-between items-center gap-2">
                        <h2 className="flex-1 text-wrap break-all leading-4">
                            <IconDatabase /> {table.name}
                        </h2>
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
                            </div>
                        )}
                    </div>
                    {table.type == 'data_warehouse' && (
                        <div className="flex flex-col">
                            {table.source && table.schema && (
                                <>
                                    <span className="card-secondary mt-2">Last Synced At</span>
                                    <span>
                                        {table.schema.last_synced_at
                                            ? humanFriendlyDetailedTime(
                                                  table.schema.last_synced_at,
                                                  'MMMM DD, YYYY',
                                                  'h:mm A'
                                              )
                                            : 'Not yet synced'}
                                    </span>
                                </>
                            )}

                            {!table.source && (
                                <>
                                    <span className="card-secondary mt-2">Files URL pattern</span>
                                    <span className="break-all">{table.url_pattern}</span>

                                    <span className="card-secondary mt-2">File format</span>
                                    <span>{table.format}</span>
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
                </>
            ) : (
                <div className="px-4 py-3 h-100 col-span-2 flex justify-center items-center" />
            )}
        </div>
    )
}

export function DeleteTableModal({
    table,
    isOpen,
    setIsOpen,
    onDelete,
}: {
    table: DatabaseSchemaTable
    isOpen: boolean
    onDelete: () => void
    setIsOpen: Dispatch<SetStateAction<boolean>>
}): JSX.Element {
    let subject

    if (table.type === 'view') {
        subject = 'view'
    } else {
        subject = 'table'
    }

    return (
        <LemonModal
            title={`Delete ${subject}?`}
            onClose={() => setIsOpen(false)}
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => setIsOpen(false)}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        status="danger"
                        onClick={() => onDelete()}
                    >{`Delete ${table.name}`}</LemonButton>
                </>
            }
            isOpen={isOpen}
        >
            <p>
                {capitalizeFirstLetter(subject)} deletion <b>cannot be undone</b>. All{' '}
                {table.type === 'view' ? 'joins' : 'views and joins'} related to this {subject} will be deleted
            </p>
        </LemonModal>
    )
}
