import { useEffect, useState } from 'react'

import { LemonButton, LemonSelect, LemonTag, lemonToast } from '@posthog/lemon-ui'

import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { ExternalDataSourceSyncSchema } from '~/types'

const getIncrementalSyncSupported = (
    schema: ExternalDataSourceSyncSchema
): { disabled: true; disabledReason: string } | { disabled: false } => {
    if (!schema.incremental_available) {
        return {
            disabled: true,
            disabledReason: "Incremental replication isn't supported on this table",
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

const getAppendOnlySyncSupported = (
    schema: ExternalDataSourceSyncSchema
): { disabled: true; disabledReason: string } | { disabled: false } => {
    if (!schema.append_available) {
        return {
            disabled: true,
            disabledReason: "Append only replication isn't supported on this table",
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
}

const getSaveDisabledReason = (
    syncType: 'full_refresh' | 'incremental' | 'append' | undefined,
    incrementalField: string | null,
    appendField: string | null
): string | undefined => {
    if (!syncType) {
        return 'You must select a sync method before saving'
    }

    if (syncType === 'incremental' && !incrementalField) {
        return 'You must select an incremental field'
    }

    if (syncType === 'append' && !appendField) {
        return 'You must select an append field'
    }
}

export const SyncMethodForm = ({ schema, onClose, onSave, saveButtonIsLoading }: SyncMethodFormProps): JSX.Element => {
    const incrementalSyncSupported = getIncrementalSyncSupported(schema)
    const appendSyncSupported = getAppendOnlySyncSupported(schema)

    const [radioValue, setRadioValue] = useState(
        schema.sync_type ?? (incrementalSyncSupported.disabled ? 'append' : 'incremental')
    )
    const [incrementalFieldValue, setIncrementalFieldValue] = useState(schema.incremental_field ?? null)
    const [appendFieldValue, setAppendFieldValue] = useState(schema.incremental_field ?? null)

    useEffect(() => {
        setRadioValue(schema.sync_type ?? (incrementalSyncSupported.disabled ? 'append' : 'incremental'))
        setIncrementalFieldValue(schema.incremental_field ?? null)
        setAppendFieldValue(schema.incremental_field ?? null)
    }, [schema.table]) // oxlint-disable-line react-hooks/exhaustive-deps

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
                            <div className="mb-4 font-normal">
                                <div className="items-center flex leading-[normal] overflow-hidden mb-1">
                                    <h4 className="mb-0 mr-2 text-base font-semibold">Incremental replication</h4>
                                    {!incrementalSyncSupported.disabled && (
                                        <LemonTag type="success">Recommended</LemonTag>
                                    )}
                                </div>
                                <p className="mb-2">
                                    When using incremental replication, we'll store the max value of the below field on
                                    each sync and only sync rows with greater or equal value on the next run.
                                </p>
                                <p className="mb-2">
                                    You should pick a field that increments or updates each time the row is updated,
                                    such as a <code>updated_at</code> timestamp.
                                </p>
                                {!incrementalSyncSupported.disabled && (
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
                                    />
                                )}
                            </div>
                        ),
                    },
                    {
                        value: 'append',
                        disabledReason:
                            (appendSyncSupported.disabled && appendSyncSupported.disabledReason) || undefined,
                        label: (
                            <div className="mb-4 font-normal">
                                <div className="items-center flex leading-[normal] overflow-hidden mb-1">
                                    <h4 className="mb-0 mr-2 text-base font-semibold">Append only replication</h4>
                                </div>
                                <p className="mb-2">
                                    When using append only replication, similar to incremental above, we'll store the
                                    max value of the below field on each sync and only sync rows with greater or equal
                                    value on the next run. But unlike incremental replication, we'll append the rows as
                                    opposed to merge them into the existing table, meaning you can have duplicate data
                                    if the value for the below field changes on a row. You should only use append only
                                    replication for sources that don't support incremental.
                                </p>
                                <p className="mb-2">
                                    You should pick a field that doesn't change each time the row is updated, such as a{' '}
                                    <code>created_at</code> timestamp.
                                </p>
                                {!appendSyncSupported.disabled && (
                                    <LemonSelect
                                        value={appendFieldValue}
                                        onChange={(newValue) => setAppendFieldValue(newValue)}
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
                                    />
                                )}
                            </div>
                        ),
                    },
                    {
                        value: 'full_refresh',
                        label: (
                            <div className="mb-6 font-normal">
                                <div className="items-center flex leading-[normal] overflow-hidden mb-1">
                                    <h4 className="mb-0 mr-2 text-base font-semibold">Full table replication</h4>
                                </div>
                                <p className="m-0">
                                    We'll replicate the whole table on every sync. This can take longer to sync and
                                    increase your monthly billing.
                                </p>
                            </div>
                        ),
                    },
                ]}
                onChange={(newValue) => setRadioValue(newValue)}
            />
            <div className="flex flex-row justify-end w-full">
                <LemonButton className="mr-3" type="secondary" onClick={onClose}>
                    Close
                </LemonButton>
                <LemonButton
                    type="primary"
                    loading={saveButtonIsLoading}
                    disabledReason={getSaveDisabledReason(radioValue, incrementalFieldValue, appendFieldValue)}
                    onClick={() => {
                        if (radioValue === 'incremental') {
                            const fieldSelected = schema.incremental_fields.find(
                                (n) => n.field === incrementalFieldValue
                            )
                            if (!fieldSelected) {
                                lemonToast.error('Selected field for incremental replication not found')
                                return
                            }

                            onSave('incremental', incrementalFieldValue, fieldSelected.field_type)
                        } else if (radioValue === 'append') {
                            const fieldSelected = schema.incremental_fields.find((n) => n.field === appendFieldValue)
                            if (!fieldSelected) {
                                lemonToast.error('Selected field for append replication not found')
                                return
                            }

                            onSave('append', appendFieldValue, fieldSelected.field_type)
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
