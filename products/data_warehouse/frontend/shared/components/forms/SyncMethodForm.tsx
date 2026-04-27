import { useEffect, useState } from 'react'

import { LemonButton, LemonSelect, LemonTag, lemonToast } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { AvailableColumn, ExternalDataSourceSyncSchema } from '~/types'

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
        incrementalFieldType: string | null,
        primaryKeyColumns: string[] | null,
        cdcTableMode?: 'consolidated' | 'cdc_only' | 'both'
    ) => void
    availableColumns?: AvailableColumn[]
    detectedPrimaryKeys?: string[] | null
    primaryKeyLocked?: boolean
    saveButtonIsLoading?: boolean
    isNewSource?: boolean
}

const getCdcSyncSupported = (
    schema: ExternalDataSourceSyncSchema
): { disabled: true; disabledReason: string } | { disabled: false } => {
    if (!schema.cdc_available) {
        return {
            disabled: true,
            disabledReason: 'This table has no primary key, which is required for CDC',
        }
    }

    return {
        disabled: false,
    }
}

const getSaveDisabledReason = (
    syncType: 'full_refresh' | 'incremental' | 'append' | 'webhook' | 'cdc' | undefined,
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

const getInitialRadioState = (
    schema: ExternalDataSourceSyncSchema,
    incrementalSyncSupported: boolean,
    appendSyncSupported: boolean
): 'full_refresh' | 'incremental' | 'append' | 'webhook' | 'cdc' => {
    if (schema.sync_type) {
        return schema.sync_type
    }
    if (schema.supports_webhooks) {
        return 'webhook'
    }
    if (schema.cdc_available) {
        return 'cdc'
    }
    if (incrementalSyncSupported) {
        return 'incremental'
    }
    if (appendSyncSupported) {
        return 'append'
    }
    return 'full_refresh'
}

export const SyncMethodForm = ({
    schema,
    onClose,
    onSave,
    availableColumns,
    detectedPrimaryKeys,
    primaryKeyLocked,
    saveButtonIsLoading,
    isNewSource,
}: SyncMethodFormProps): JSX.Element => {
    const incrementalSyncSupported = getIncrementalSyncSupported(schema)
    const appendSyncSupported = getAppendOnlySyncSupported(schema)
    const cdcSyncSupported = getCdcSyncSupported(schema)

    const columns = availableColumns ?? schema.available_columns ?? []
    const resolvedDetectedPks = detectedPrimaryKeys ?? schema.detected_primary_keys ?? null

    const [radioValue, setRadioValue] = useState(() =>
        getInitialRadioState(schema, !incrementalSyncSupported.disabled, !appendSyncSupported.disabled)
    )
    const [incrementalFieldValue, setIncrementalFieldValue] = useState(schema.incremental_field ?? null)
    const [appendFieldValue, setAppendFieldValue] = useState(schema.incremental_field ?? null)
    // Prefill detected PKs only when the selector is editable. For locked schemas
    // (already synced) the backend rejects any PK diff, so prefilling from detected
    // would silently turn unrelated edits into "Primary key cannot be changed" errors.
    const [primaryKeyColumns, setPrimaryKeyColumns] = useState<string[]>(
        schema.primary_key_columns ?? (primaryKeyLocked ? [] : (resolvedDetectedPks ?? []))
    )
    const [cdcTableMode, setCdcTableMode] = useState<'consolidated' | 'cdc_only' | 'both'>(
        schema.cdc_table_mode ?? 'consolidated'
    )

    useEffect(() => {
        setRadioValue(
            schema.sync_type ??
                (schema.supports_webhooks ? 'webhook' : incrementalSyncSupported.disabled ? 'append' : 'incremental')
        )
        setIncrementalFieldValue(schema.incremental_field ?? null)
        setAppendFieldValue(schema.incremental_field ?? null)
        setPrimaryKeyColumns(schema.primary_key_columns ?? (primaryKeyLocked ? [] : (resolvedDetectedPks ?? [])))
    }, [schema.table]) // oxlint-disable-line react-hooks/exhaustive-deps

    const radioOptions: {
        value: 'webhook' | 'incremental' | 'append' | 'full_refresh' | 'cdc'
        disabledReason?: string
        label: JSX.Element
    }[] = []

    if (schema.supports_webhooks) {
        radioOptions.push({
            value: 'webhook',
            label: (
                <div className="mb-4 font-normal">
                    <div className="items-center flex leading-[normal] overflow-hidden mb-1">
                        <h4 className="mb-0 mr-2 text-base font-semibold">Webhook</h4>
                        <LemonTag type="success">Recommended</LemonTag>
                    </div>
                    <p className="mb-2">
                        When using webhook sync, we'll receive updates from your source via webhooks. This provides the
                        fastest data freshness with minimal sync overhead.
                    </p>
                    {isNewSource && (
                        <LemonBanner type="info" className="mt-2">
                            The webhook will be configured in the next step.
                        </LemonBanner>
                    )}
                </div>
            ),
        })
    }

    if (schema.cdc_available) {
        radioOptions.push({
            value: 'cdc',
            disabledReason: (cdcSyncSupported.disabled && cdcSyncSupported.disabledReason) || undefined,
            label: (
                <div className="mb-4 font-normal rounded border border-success/40 bg-success-highlight/40 p-3">
                    <div className="items-center flex leading-[normal] overflow-hidden mb-1">
                        <h4 className="mb-0 mr-2 text-base font-semibold">CDC (change data capture)</h4>
                        {!schema.supports_webhooks && <LemonTag type="success">Recommended</LemonTag>}
                    </div>
                    <p className="mb-2">
                        Capture inserts, updates, and deletes in real-time via logical replication. Keeps PostHog in
                        sync with the source continuously and handles row deletes — unlike incremental or append.
                        Requires a primary key on the source table.
                    </p>
                    {radioValue === 'cdc' && (
                        <div className="mt-3 pt-3 border-t border-success/30">
                            <p className="text-sm font-semibold mb-2">Output tables</p>
                            <LemonRadio
                                radioPosition="top"
                                value={cdcTableMode}
                                onChange={(newValue) =>
                                    setCdcTableMode(newValue as 'consolidated' | 'cdc_only' | 'both')
                                }
                                options={[
                                    {
                                        value: 'consolidated',
                                        label: (
                                            <div className="font-normal mb-2">
                                                <div className="font-semibold">Consolidated table only</div>
                                                <p className="m-0 text-secondary text-sm">
                                                    Deduplicates changes — only the latest state per row is stored.
                                                </p>
                                            </div>
                                        ),
                                    },
                                    {
                                        value: 'cdc_only',
                                        label: (
                                            <div className="font-normal mb-2">
                                                <div className="font-semibold">CDC history table only</div>
                                                <p className="m-0 text-secondary text-sm">
                                                    Full audit trail in a <code>_cdc</code>-suffixed table with{' '}
                                                    <code>valid_from</code> / <code>valid_to</code> columns.
                                                </p>
                                            </div>
                                        ),
                                    },
                                    {
                                        value: 'both',
                                        label: (
                                            <div className="font-normal mb-2">
                                                <div className="font-semibold">Both</div>
                                                <p className="m-0 text-secondary text-sm">
                                                    CDC history table plus an auto-generated view for the current state
                                                    (<code>valid_to IS NULL</code>).
                                                </p>
                                            </div>
                                        ),
                                    },
                                ]}
                            />
                        </div>
                    )}
                </div>
            ),
        })
    }

    radioOptions.push(
        {
            value: 'incremental',
            disabledReason: (incrementalSyncSupported.disabled && incrementalSyncSupported.disabledReason) || undefined,
            label: (
                <div className="mb-4 font-normal">
                    <div className="items-center flex leading-[normal] overflow-hidden mb-1">
                        <h4 className="mb-0 mr-2 text-base font-semibold">Incremental replication</h4>
                        {!incrementalSyncSupported.disabled && !schema.supports_webhooks && !schema.cdc_available && (
                            <LemonTag type="success">Recommended</LemonTag>
                        )}
                    </div>
                    <p className="mb-2">
                        When using incremental replication, we'll store the max value of the below field on each sync
                        and only sync rows with greater or equal value on the next run.
                    </p>
                    <p className="mb-2">
                        You should pick a field that increments or updates each time the row is updated, such as a{' '}
                        <code>updated_at</code> timestamp.
                    </p>
                    {!incrementalSyncSupported.disabled && (
                        <>
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
                            {radioValue === 'incremental' &&
                                incrementalFieldValue &&
                                schema.incremental_fields.find((n) => n.field === incrementalFieldValue)?.nullable && (
                                    <LemonBanner type="warning" className="mt-2">
                                        This field is nullable. Any rows where <code>{incrementalFieldValue}</code> is
                                        null will not be synced.
                                    </LemonBanner>
                                )}
                            {radioValue === 'incremental' && columns.length > 0 && (
                                <>
                                    <p className="mt-4 mb-2">
                                        Optionally, select one or more columns to use as the primary key for
                                        deduplication. If not set, PostHog will attempt to auto-detect the primary key
                                        from the source.
                                    </p>
                                    <LemonInputSelect
                                        mode="multiple"
                                        value={primaryKeyColumns}
                                        onChange={(newValue) => !primaryKeyLocked && setPrimaryKeyColumns(newValue)}
                                        disabled={primaryKeyLocked}
                                        options={columns.map((col) => ({
                                            key: col.field,
                                            label: `${col.label} (${col.type})`,
                                        }))}
                                        placeholder={
                                            resolvedDetectedPks
                                                ? `Auto-detected: ${resolvedDetectedPks.join(', ')}`
                                                : 'No primary key detected'
                                        }
                                    />
                                    {primaryKeyLocked && (
                                        <LemonBanner type="info" className="mt-2">
                                            Primary key cannot be changed after data has been synced. Delete the synced
                                            data first to change it.
                                        </LemonBanner>
                                    )}
                                    {primaryKeyColumns.length === 0 && !resolvedDetectedPks && !primaryKeyLocked && (
                                        <LemonBanner type="info" className="mt-2">
                                            No primary key could be auto-detected from the source. Select one manually
                                            to enable incremental sync, or use full table replication instead.
                                        </LemonBanner>
                                    )}
                                    {primaryKeyColumns.length > 0 &&
                                        primaryKeyColumns.some(
                                            (pk) => columns.find((col) => col.field === pk)?.nullable
                                        ) && (
                                            <LemonBanner type="warning" className="mt-2">
                                                One or more selected primary key columns are nullable. Rows with null
                                                values may cause issues with deduplication.
                                            </LemonBanner>
                                        )}
                                </>
                            )}
                        </>
                    )}
                </div>
            ),
        },
        {
            value: 'append',
            disabledReason: (appendSyncSupported.disabled && appendSyncSupported.disabledReason) || undefined,
            label: (
                <div className="mb-4 font-normal">
                    <div className="items-center flex leading-[normal] overflow-hidden mb-1">
                        <h4 className="mb-0 mr-2 text-base font-semibold">Append only replication</h4>
                    </div>
                    <p className="mb-2">
                        When using append only replication, similar to incremental above, we'll store the max value of
                        the below field on each sync and only sync rows with greater or equal value on the next run. But
                        unlike incremental replication, we'll append the rows as opposed to merge them into the existing
                        table, meaning you can have duplicate data if the value for the below field changes on a row.
                        You should only use append only replication for sources that don't support incremental.
                    </p>
                    <p className="mb-2">
                        You should pick a field that doesn't change each time the row is updated, such as a{' '}
                        <code>created_at</code> timestamp.
                    </p>
                    {!appendSyncSupported.disabled && (
                        <>
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
                            {radioValue === 'append' &&
                                appendFieldValue &&
                                schema.incremental_fields.find((n) => n.field === appendFieldValue)?.nullable && (
                                    <LemonBanner type="warning" className="mt-2">
                                        This field is nullable. Any rows where <code>{appendFieldValue}</code> is null
                                        will not be synced.
                                    </LemonBanner>
                                )}
                        </>
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
                        We'll replicate the whole table on every sync. This can take longer to sync and increase your
                        monthly billing.
                    </p>
                </div>
            ),
        }
    )

    return (
        <>
            <LemonRadio
                radioPosition="top"
                value={radioValue}
                options={radioOptions}
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
                        if (radioValue === 'webhook') {
                            onSave('webhook', null, null, null)
                        } else if (radioValue === 'cdc') {
                            onSave('cdc', null, null, null, cdcTableMode)
                        } else if (radioValue === 'incremental') {
                            const fieldSelected = schema.incremental_fields.find(
                                (n) => n.field === incrementalFieldValue
                            )
                            if (!fieldSelected) {
                                lemonToast.error('Selected field for incremental replication not found')
                                return
                            }

                            onSave(
                                'incremental',
                                incrementalFieldValue,
                                fieldSelected.field_type,
                                primaryKeyColumns.length > 0 ? primaryKeyColumns : null
                            )
                        } else if (radioValue === 'append') {
                            const fieldSelected = schema.incremental_fields.find((n) => n.field === appendFieldValue)
                            if (!fieldSelected) {
                                lemonToast.error('Selected field for append replication not found')
                                return
                            }

                            onSave('append', appendFieldValue, fieldSelected.field_type, null)
                        } else {
                            onSave('full_refresh', null, null, null)
                        }
                    }}
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
