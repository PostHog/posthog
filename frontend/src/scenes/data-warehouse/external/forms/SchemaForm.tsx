import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonCheckbox, LemonModal, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { useFloatingContainer } from 'lib/hooks/useFloatingContainerContext'
import { SyncTypeLabelMap } from 'scenes/data-warehouse/utils'

import { ExternalDataSourceSyncSchema } from '~/types'

import { sourceWizardLogic } from '../../new/sourceWizardLogic'
import { SyncMethodForm } from './SyncMethodForm'

export default function SchemaForm(): JSX.Element {
    const containerRef = useFloatingContainer()
    const { toggleSchemaShouldSync, openSyncMethodModal, toggleAllTables } = useActions(sourceWizardLogic)
    const { databaseSchema, tablesAllToggledOn } = useValues(sourceWizardLogic)

    const onClickCheckbox = (schema: ExternalDataSourceSyncSchema, checked: boolean): void => {
        if (schema.sync_type === null) {
            openSyncMethodModal(schema)
            return
        }
        toggleSchemaShouldSync(schema, checked)
    }

    // scroll to top of container
    useEffect(() => {
        containerRef?.scrollTo({ top: 0, left: 0, behavior: 'smooth' })
    }, [containerRef])

    return (
        <>
            <div className="flex flex-col gap-2">
                <div>
                    <LemonTable
                        emptyState="No schemas found"
                        dataSource={databaseSchema}
                        columns={[
                            {
                                title: (
                                    <LemonCheckbox
                                        checked={tablesAllToggledOn}
                                        onChange={(checked) => toggleAllTables(checked)}
                                    />
                                ),
                                width: 0,
                                key: 'enabled',
                                render: function RenderEnabled(_, schema) {
                                    return (
                                        <LemonCheckbox
                                            checked={schema.should_sync}
                                            onChange={(checked) => onClickCheckbox(schema, checked)}
                                        />
                                    )
                                },
                            },
                            {
                                title: 'Table',
                                key: 'table',
                                render: function RenderTable(_, schema) {
                                    return (
                                        <span
                                            className="font-mono cursor-pointer"
                                            onClick={() => onClickCheckbox(schema, !schema.should_sync)}
                                        >
                                            {schema.table}
                                        </span>
                                    )
                                },
                            },
                            {
                                title: 'Rows',
                                key: 'rows',
                                isHidden: !databaseSchema.some((schema) => schema.rows),
                                render: function RenderRows(_, schema) {
                                    return schema.rows != null ? schema.rows : 'Unknown'
                                },
                            },
                            {
                                key: 'sync_field',
                                title: 'Sync field',
                                align: 'right',
                                tooltip:
                                    'Incremental and append-only refresh methods key on a unique field to determine the most up-to-date data.',
                                isHidden: !databaseSchema.some((schema) => schema.sync_type),
                                render: function RenderSyncType(_, schema) {
                                    if (
                                        schema.sync_type !== 'full_refresh' &&
                                        schema.sync_type !== null &&
                                        schema.incremental_field
                                    ) {
                                        const field =
                                            schema.incremental_fields.find(
                                                (f) => f.field == schema.incremental_field
                                            ) ?? null
                                        if (field) {
                                            return (
                                                <>
                                                    <span className="leading-5">{field.label}</span>
                                                    <LemonTag className="ml-2" type="success">
                                                        {field.type}
                                                    </LemonTag>
                                                </>
                                            )
                                        }
                                    }
                                },
                            },
                            {
                                key: 'sync_type',
                                title: 'Sync method',
                                align: 'right',
                                tooltip:
                                    'Full refresh will refresh the full table on every sync, whereas incremental will only sync new and updated rows since the last sync',
                                render: function RenderSyncType(_, schema) {
                                    if (!schema.sync_type) {
                                        return (
                                            <div className="justify-end flex">
                                                <LemonButton
                                                    className="my-1"
                                                    type="primary"
                                                    onClick={() => openSyncMethodModal(schema)}
                                                    size="small"
                                                >
                                                    Configure
                                                </LemonButton>
                                            </div>
                                        )
                                    }

                                    return (
                                        <div className="justify-end flex">
                                            <LemonButton
                                                className="my-1"
                                                size="small"
                                                type="secondary"
                                                onClick={() => openSyncMethodModal(schema)}
                                            >
                                                {SyncTypeLabelMap[schema.sync_type]}
                                            </LemonButton>
                                        </div>
                                    )
                                },
                            },
                        ]}
                    />
                </div>
            </div>
            <SyncMethodModal />
        </>
    )
}

const SyncMethodModal = (): JSX.Element => {
    const { cancelSyncMethodModal, updateSchemaSyncType, toggleSchemaShouldSync } = useActions(sourceWizardLogic)
    const { syncMethodModalOpen, currentSyncMethodModalSchema } = useValues(sourceWizardLogic)

    if (!currentSyncMethodModalSchema) {
        return <></>
    }

    return (
        <LemonModal
            title={
                <>
                    Sync method for <span className="font-mono">{currentSyncMethodModalSchema.table}</span>
                </>
            }
            isOpen={syncMethodModalOpen}
            onClose={cancelSyncMethodModal}
        >
            <SyncMethodForm
                schema={currentSyncMethodModalSchema}
                onClose={cancelSyncMethodModal}
                onSave={(syncType, incrementalField, incrementalFieldType) => {
                    if (syncType === 'incremental' || syncType === 'append') {
                        updateSchemaSyncType(
                            currentSyncMethodModalSchema,
                            syncType,
                            incrementalField,
                            incrementalFieldType
                        )
                    } else {
                        updateSchemaSyncType(currentSyncMethodModalSchema, syncType ?? null, null, null)
                    }

                    toggleSchemaShouldSync(currentSyncMethodModalSchema, true)
                    cancelSyncMethodModal()
                }}
            />
        </LemonModal>
    )
}
