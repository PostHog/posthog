import { LemonButton, LemonSelect, LemonTag, lemonToast } from '@posthog/lemon-ui'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { useEffect, useState } from 'react'

import { ExternalDataSourceSyncSchema } from '~/types'

const getIncrementalSyncSupported = (
    schema: ExternalDataSourceSyncSchema
): { disabled: true; disabledReason: string } | { disabled: false } => {
    if (!schema.incremental_available) {
        return {
            disabled: true,
            disabledReason: "Incremental append replication isn't supported on this table",
        }
    }

    if (schema.incremental_fields.length === 0) {
        return {
            disabled: true,
            disabledReason: 'No incremental fields found on table',
        }
    }

    return {
        disabled: false,
    }
}

interface SyncMethodFormProps {
    schema: ExternalDataSourceSyncSchema
    onClose: () => void
    onSave: (
        syncType: ExternalDataSourceSyncSchema['sync_type'],
        incrementalField: string | null,
        incrementalFieldType: string | null
    ) => void
    saveButtonIsLoading?: boolean
    showRefreshMessageOnChange?: boolean
}

const hasInputChanged = (
    newSchemaSyncType: ExternalDataSourceSyncSchema['sync_type'],
    newSchemaIncrementalField: string | null,
    originalSchemaSyncType: ExternalDataSourceSyncSchema['sync_type'],
    originalSchemaIncrementalField: string | null
): boolean => {
    if (originalSchemaSyncType !== newSchemaSyncType) {
        return true
    }

    if (newSchemaSyncType === 'incremental' && newSchemaIncrementalField !== originalSchemaIncrementalField) {
        return true
    }

    return false
}

const getSaveDisabledReason = (
    syncType: 'full_refresh' | 'incremental' | undefined,
    incrementalField: string | null
): string | undefined => {
    if (!syncType) {
        return 'You must select a sync method before saving'
    }

    if (syncType === 'incremental' && !incrementalField) {
        return 'You must select an incremental field'
    }
}

export const SyncMethodForm = ({
    schema,
    onClose,
    onSave,
    saveButtonIsLoading,
    showRefreshMessageOnChange,
}: SyncMethodFormProps): JSX.Element => {
    const [originalSchemaSyncType] = useState(schema.sync_type ?? null)
    const [originalSchemaIncrementalField] = useState(schema.incremental_field ?? null)

    const [radioValue, setRadioValue] = useState(schema.sync_type ?? undefined)
    const [incrementalFieldValue, setIncrementalFieldValue] = useState(schema.incremental_field ?? null)

    useEffect(() => {
        setRadioValue(schema.sync_type ?? undefined)
        setIncrementalFieldValue(schema.incremental_field ?? null)
    }, [schema.table])

    const incrementalSyncSupported = getIncrementalSyncSupported(schema)

    const inputChanged = hasInputChanged(
        radioValue ?? null,
        incrementalFieldValue,
        originalSchemaSyncType,
        originalSchemaIncrementalField
    )
    const showRefreshMessage = inputChanged && showRefreshMessageOnChange

    return (
        <>
            <LemonRadio
                radioPosition="top"
                value={radioValue}
                options={[
                    {
                        value: 'incremental',
                        disabledReason:
                            (incrementalSyncSupported.disabled && incrementalSyncSupported.disabledReason) || undefined,
                        label: (
                            <div className="mb-6 font-normal">
                                <div className="items-center flex leading-[normal] overflow-hidden mb-2.5">
                                    <h2 className="mb-0 mr-2">Incremental append replication</h2>
                                    {!incrementalSyncSupported.disabled && (
                                        <LemonTag type="success">Recommended</LemonTag>
                                    )}
                                </div>
                                <p>
                                    When using incremental append replication, we'll store the max value of the below
                                    field on each sync and only sync rows with greater or equal value on the next run.
                                </p>
                                <p>
                                    You should pick a field that increments for each row, such as a{' '}
                                    <code>created_at</code> timestamp.
                                </p>
                                <p>
                                    This method will append all new rows to your existing table - this means duplicate
                                    data can exist if the incremental field updates for updated rows (such as when using
                                    an <code>updated_at</code> field)
                                </p>
                                <LemonSelect
                                    value={incrementalFieldValue}
                                    onChange={(newValue) => setIncrementalFieldValue(newValue)}
                                    options={
                                        schema.incremental_fields.map((n) => ({
                                            value: n.field,
                                            label: (
                                                <>
                                                    <span className="leading-5">{n.label}</span>
                                                    <LemonTag className="ml-2" type="success">
                                                        {n.type}
                                                    </LemonTag>
                                                </>
                                            ),
                                        })) ?? []
                                    }
                                    disabledReason={incrementalSyncSupported.disabled ? '' : undefined}
                                />
                            </div>
                        ),
                    },
                    {
                        value: 'full_refresh',
                        label: (
                            <div className="mb-6 font-normal">
                                <div className="items-center flex leading-[normal] overflow-hidden mb-2.5">
                                    <h2 className="mb-0 mr-2">Full table replication</h2>
                                </div>
                                <p>
                                    We'll replicate the whole table on every sync. This can take longer to sync and
                                    increase your monthly billing.
                                </p>
                            </div>
                        ),
                    },
                ]}
                onChange={(newValue) => setRadioValue(newValue)}
            />
            {showRefreshMessage && (
                <p className="text-danger">
                    Note: Changing the sync type or incremental append replication field will trigger a full table
                    refresh
                </p>
            )}
            <div className="flex flex-row justify-end w-full">
                <LemonButton className="mr-3" type="secondary" onClick={onClose}>
                    Close
                </LemonButton>
                <LemonButton
                    type="primary"
                    loading={saveButtonIsLoading}
                    disabledReason={getSaveDisabledReason(radioValue, incrementalFieldValue)}
                    onClick={() => {
                        if (radioValue === 'incremental') {
                            const fieldSelected = schema.incremental_fields.find(
                                (n) => n.field === incrementalFieldValue
                            )
                            if (!fieldSelected) {
                                lemonToast.error('Selected field for incremental append replication not found')
                                return
                            }

                            onSave('incremental', incrementalFieldValue, fieldSelected.field_type)
                        } else {
                            onSave('full_refresh', null, null)
                        }
                    }}
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
