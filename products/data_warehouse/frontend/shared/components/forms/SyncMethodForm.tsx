import { forwardRef, useEffect, useId, useImperativeHandle, useState } from 'react'

import { LemonButton, LemonInput, LemonSelect, LemonTag, Link, lemonToast } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { AvailableColumn, ExternalDataSourceSyncSchema } from '~/types'

const LOOKBACK_UNIT_SECONDS = {
    minutes: 60,
    hours: 3600,
    days: 86400,
} as const
type LookbackUnit = keyof typeof LOOKBACK_UNIT_SECONDS

// Only timestamp/date incremental fields support a lookback window; the watermark for these is a
// point in time we can safely re-read from. Mirrors IncrementalFieldType on the backend.
const LOOKBACK_ELIGIBLE_TYPES = new Set(['datetime', 'date', 'timestamp'])
export const isLookbackEligibleType = (fieldType: string | null | undefined): boolean =>
    !!fieldType && LOOKBACK_ELIGIBLE_TYPES.has(fieldType)

// A history version starts at the cursor value. A date stays equal for every change made that day, so only a
// cursor with a time can keep history. Mirrors HISTORY_CURSOR_TYPES on the backend.
const HISTORY_CURSOR_TYPES = new Set(['datetime', 'timestamp'])

export const secondsToLookbackParts = (
    seconds: number | null | undefined
): { amount: number | null; unit: LookbackUnit } => {
    if (!seconds || seconds <= 0) {
        return { amount: null, unit: 'hours' }
    }
    // Show the largest unit the value divides into evenly so a 2-day window reads as "2 days", not "48 hours".
    for (const unit of ['days', 'hours', 'minutes'] as LookbackUnit[]) {
        if (seconds % LOOKBACK_UNIT_SECONDS[unit] === 0) {
            return { amount: seconds / LOOKBACK_UNIT_SECONDS[unit], unit }
        }
    }
    // Floor (not round) so a non-divisible value never displays as more than it is and then
    // saves back the inflated number — e.g. 90 s shows "1 minute" and round-trips to 60 s.
    return { amount: Math.floor(seconds / 60), unit: 'minutes' }
}

const getIncrementalSyncSupported = (
    schema: ExternalDataSourceSyncSchema
): { disabled: true; disabledReason: string } | { disabled: false } => {
    if (!schema.incremental_available) {
        return {
            disabled: true,
            disabledReason:
                "Incremental replication isn't available for this table. Usually this is because the table has no timestamp, date, or auto-incrementing numeric column to track new rows. Some sources also don't support it for every table. Use full table replication instead.",
        }
    }

    if (schema.incremental_fields.length === 0) {
        return {
            disabled: true,
            disabledReason:
                'Incremental replication needs a timestamp, date, or auto-incrementing numeric column to track new rows, and none was found on this table',
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
            disabledReason:
                "Append only replication isn't available for this table. Usually this is because the table has no timestamp, date, or auto-incrementing numeric column to track new rows. Some sources also don't support it for every table. Use full table replication instead.",
        }
    }

    if (schema.incremental_fields.length === 0) {
        return {
            disabled: true,
            disabledReason:
                'Append only replication needs a timestamp, date, or auto-incrementing numeric column to track new rows, and none was found on this table',
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
        cdcTableMode?: 'consolidated' | 'cdc_only' | 'both',
        incrementalFieldLookbackSeconds?: number | null
    ) => void
    availableColumns?: AvailableColumn[]
    detectedPrimaryKeys?: string[] | null
    primaryKeyDetectionSupported?: boolean
    primaryKeyLocked?: boolean
    saveButtonIsLoading?: boolean
    isNewSource?: boolean
    /** Hide the built-in Close and Save buttons so a parent can render its own save action outside the form. */
    hideFooter?: boolean
    /** Called whenever the form's save validity changes. Useful when rendering an external Save button. */
    onSaveDisabledReasonChange?: (disabledReason: string | undefined) => void
    /** The source can run CDC, so the option is shown even when this table can't pick it yet. */
    sourceSupportsCdc?: boolean
    /** Where CDC is turned on for the source. */
    sourceConfigurationUrl?: string
}

type SyncMethodValue = 'webhook' | 'incremental' | 'append' | 'full_refresh' | 'cdc' | 'xmin'

interface SyncMethodOption {
    value: SyncMethodValue
    disabledReason?: string
    label: JSX.Element
}

export interface SyncMethodFormHandle {
    triggerSave: () => void
}

// The API sends null when CDC is off for the source, and false when it's on but the table has no primary key.
export const getCdcAvailability = (
    schema: ExternalDataSourceSyncSchema
): { isCdcOnForSource: boolean; tableHasPrimaryKeyForCdc: boolean; canPickCdc: boolean } => {
    const isCdcOnForSource = schema.cdc_available != null
    const tableHasPrimaryKeyForCdc = schema.cdc_available === true
    return { isCdcOnForSource, tableHasPrimaryKeyForCdc, canPickCdc: isCdcOnForSource && tableHasPrimaryKeyForCdc }
}

const CDC_OFF_FOR_SOURCE_REASON = 'Turn on CDC for this source first'

const getCdcSyncSupported = (
    schema: ExternalDataSourceSyncSchema
): { disabled: true; disabledReason: string } | { disabled: false } => {
    const { isCdcOnForSource, tableHasPrimaryKeyForCdc } = getCdcAvailability(schema)
    if (!isCdcOnForSource) {
        return { disabled: true, disabledReason: CDC_OFF_FOR_SOURCE_REASON }
    }
    if (!tableHasPrimaryKeyForCdc) {
        return { disabled: true, disabledReason: 'This table needs a primary key on the source to use CDC' }
    }

    return {
        disabled: false,
    }
}

// xmin is offered only when the source advertises it for the table.
export const shouldOfferXmin = (schema: ExternalDataSourceSyncSchema): boolean =>
    !schema.webhook_only && !!schema.xmin_available

export const getSaveDisabledReason = (
    syncType: 'full_refresh' | 'incremental' | 'append' | 'webhook' | 'cdc' | 'xmin' | undefined,
    incrementalField: string | null,
    appendField: string | null,
    mergeKey: string[] | null,
    keyRequired: boolean,
    replicationKeyRequired: boolean
): string | undefined => {
    if (!syncType) {
        return 'You must select a sync method before saving'
    }

    if (syncType === 'incremental' && !incrementalField) {
        return 'You must select an incremental field'
    }

    // An incremental sync merges rows on a key. Saved without one, the table syncs once and then
    // fails on every later run, so the key is required here rather than at the first merge.
    if (syncType === 'incremental' && keyRequired && !mergeKey?.length) {
        return 'Select primary key columns, or use full table replication instead'
    }

    if (syncType === 'append' && !appendField) {
        return 'You must select an append field'
    }

    // The schema API refuses CDC and xmin without a key, whatever the source.
    if ((syncType === 'cdc' || syncType === 'xmin') && replicationKeyRequired && !mergeKey?.length) {
        return 'This table has no primary key on the source. Add one there, or use full table replication instead'
    }
}

export const getInitialRadioState = (
    schema: ExternalDataSourceSyncSchema,
    incrementalSyncSupported: boolean,
    appendSyncSupported: boolean,
    keyResolvable: boolean
): 'full_refresh' | 'incremental' | 'append' | 'webhook' | 'cdc' | 'xmin' => {
    if (schema.sync_type) {
        return schema.sync_type
    }
    // Webhook-only schemas can only ever use the webhook sync method.
    if (schema.webhook_only) {
        return 'webhook'
    }
    if (schema.supports_webhooks) {
        return 'webhook'
    }
    if (getCdcAvailability(schema).canPickCdc) {
        return 'cdc'
    }
    // Offering incremental to a table with no key only leads to a sync that fails on its second
    // run, so a keyless table falls through to a method it can actually run.
    if (incrementalSyncSupported && keyResolvable) {
        return 'incremental'
    }
    if (appendSyncSupported) {
        return 'append'
    }
    return 'full_refresh'
}

export const SyncMethodForm = forwardRef<SyncMethodFormHandle, SyncMethodFormProps>(function SyncMethodForm(
    {
        schema,
        onClose,
        onSave,
        availableColumns,
        detectedPrimaryKeys,
        primaryKeyDetectionSupported,
        primaryKeyLocked,
        saveButtonIsLoading,
        isNewSource,
        hideFooter,
        onSaveDisabledReasonChange,
        sourceSupportsCdc,
        sourceConfigurationUrl,
    },
    ref
): JSX.Element {
    const incrementalSyncSupported = getIncrementalSyncSupported(schema)
    const appendSyncSupported = getAppendOnlySyncSupported(schema)
    const cdcSyncSupported = getCdcSyncSupported(schema)
    const { isCdcOnForSource, canPickCdc } = getCdcAvailability(schema)

    // An empty discovered list means "not discovered", not "this relation has no columns": a
    // Redshift materialized view under a restricted role is listed from the stored metadata alone.
    // The API judges an incremental switch against that stored list, so the key picker offers it
    // too — otherwise the switch is refused with no way to satisfy it.
    const columns = availableColumns?.length ? availableColumns : (schema.available_columns ?? [])
    const resolvedDetectedPks = detectedPrimaryKeys ?? schema.detected_primary_keys ?? null
    // A key is only asked for when the source reads keys off the table and the columns are
    // known. A source that declares its key in code resolves it at sync time, and with no
    // column list there is nothing to pick from.
    const keyRequired =
        (primaryKeyDetectionSupported ?? schema.primary_key_detection_supported ?? false) && columns.length > 0
    const keyResolvable = !keyRequired || !!(schema.primary_key_columns?.length || resolvedDetectedPks?.length)

    const defaultField = schema.incremental_field ?? schema.incremental_fields[0]?.field ?? null

    const [radioValue, setRadioValue] = useState(() =>
        getInitialRadioState(schema, !incrementalSyncSupported.disabled, !appendSyncSupported.disabled, keyResolvable)
    )
    const [incrementalFieldValue, setIncrementalFieldValue] = useState(defaultField)
    const [appendFieldValue, setAppendFieldValue] = useState(defaultField)
    // Prefill detected PKs only when the selector is editable. A locked schema already has a key
    // the backend refuses to swap, so prefilling from detected would silently turn unrelated edits
    // into "Primary key cannot be changed" errors.
    const [primaryKeyColumns, setPrimaryKeyColumns] = useState<string[]>(
        schema.primary_key_columns ?? (primaryKeyLocked ? [] : (resolvedDetectedPks ?? []))
    )
    const [cdcTableMode, setCdcTableMode] = useState<'consolidated' | 'cdc_only' | 'both'>(
        schema.cdc_table_mode ?? 'consolidated'
    )
    const initialLookback = secondsToLookbackParts(schema.incremental_field_lookback_seconds)
    const [lookbackAmount, setLookbackAmount] = useState<number | null>(initialLookback.amount)
    const [lookbackUnit, setLookbackUnit] = useState<LookbackUnit>(initialLookback.unit)

    useEffect(() => {
        setRadioValue(
            getInitialRadioState(
                schema,
                !incrementalSyncSupported.disabled,
                !appendSyncSupported.disabled,
                keyResolvable
            )
        )
        setIncrementalFieldValue(defaultField)
        setAppendFieldValue(defaultField)
        setPrimaryKeyColumns(schema.primary_key_columns ?? (primaryKeyLocked ? [] : (resolvedDetectedPks ?? [])))
        const resetLookback = secondsToLookbackParts(schema.incremental_field_lookback_seconds)
        setLookbackAmount(resetLookback.amount)
        setLookbackUnit(resetLookback.unit)
    }, [schema.table]) // oxlint-disable-line react-hooks/exhaustive-deps

    const lookbackSeconds =
        lookbackAmount != null && lookbackAmount > 0 ? lookbackAmount * LOOKBACK_UNIT_SECONDS[lookbackUnit] : null

    // New-source setup reads CDC keys from the source catalog itself, so the key requirement only
    // applies to an existing source's tables.
    const replicationKeyRequired = !isNewSource
    // CDC and xmin can't take a picked key. CDC deletes carry only the source's replica identity
    // (its primary key by default), and the xmin reader resolves the key from the source itself, so
    // a different key would stop deletes and upserts from matching rows.
    const sourcePrimaryKeys = resolvedDetectedPks ?? schema.primary_key_columns ?? null
    // The API refuses to replace a key once data has synced, so a synced key that differs from the source's
    // can only be fixed by deleting the synced data.
    const syncedPrimaryKeys = primaryKeyLocked ? (schema.primary_key_columns ?? []) : []
    const lockedPrimaryKeyMismatchReason =
        (radioValue === 'cdc' || radioValue === 'xmin') &&
        replicationKeyRequired &&
        syncedPrimaryKeys.length > 0 &&
        !!sourcePrimaryKeys?.length &&
        syncedPrimaryKeys.join(',') !== sourcePrimaryKeys.join(',')
            ? `The synced data uses the primary key ${syncedPrimaryKeys.join(', ')}, but the source table's primary key is ${sourcePrimaryKeys.join(', ')}. Delete the synced data first, then save.`
            : undefined
    const sourcePrimaryKeyNote = sourcePrimaryKeys?.length ? (
        <>
            <p className="m-0">
                Uses the primary key on the source table: <code>{sourcePrimaryKeys.join(', ')}</code>
            </p>
            {lockedPrimaryKeyMismatchReason && (
                <LemonBanner type="warning" className="mt-2">
                    {lockedPrimaryKeyMismatchReason}
                </LemonBanner>
            )}
        </>
    ) : (
        <LemonBanner type="warning">
            No primary key was found on the source table. Add one there, or use full table replication instead.
        </LemonBanner>
    )
    const primaryKeyPicker =
        columns.length > 0 ? (
            <>
                <p className="mb-2">
                    Optionally, select one or more columns to use as the primary key for deduplication. If not set,
                    PostHog will attempt to auto-detect the primary key from the source.
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
                        Primary key cannot be changed after data has been synced. Delete the synced data first to change
                        it.
                    </LemonBanner>
                )}
                {primaryKeyColumns.length === 0 && !resolvedDetectedPks && !primaryKeyLocked && (
                    <LemonBanner type="info" className="mt-2">
                        No primary key could be auto-detected from the source. Select one manually to enable incremental
                        sync, or use full table replication instead.
                    </LemonBanner>
                )}
                {primaryKeyColumns.some((pk) => columns.find((col) => col.field === pk)?.nullable) && (
                    <LemonBanner type="warning" className="mt-2">
                        One or more selected primary key columns are nullable. Rows with null values may cause issues
                        with deduplication.
                    </LemonBanner>
                )}
            </>
        ) : null
    const historyFieldType = schema.incremental_fields.find((n) => n.field === incrementalFieldValue)?.field_type
    const historyAvailable =
        !!schema.incremental_history_available && !!historyFieldType && HISTORY_CURSOR_TYPES.has(historyFieldType)
    // A saved history mode stays shown while its field is unchanged, also when the source stopped reporting the
    // field as a date and time, so an unrelated save doesn't turn history off.
    const keepsSavedHistory =
        schema.sync_type === 'incremental' &&
        incrementalFieldValue === schema.incremental_field &&
        (schema.cdc_table_mode ?? 'consolidated') !== 'consolidated'
    const incrementalTableMode = historyAvailable || keepsSavedHistory ? cdcTableMode : 'consolidated'

    const webhookOptions: SyncMethodOption[] = schema.supports_webhooks
        ? [
              {
                  value: 'webhook',
                  label: (
                      <div className="mb-4 font-normal">
                          <div className="items-center flex leading-[normal] overflow-hidden mb-1">
                              <h4 className="mb-0 mr-2 text-base font-semibold">Webhook</h4>
                              <LemonTag type="success">Recommended</LemonTag>
                          </div>
                          <p className="mb-2">
                              When using webhook sync, we'll receive updates from your source via webhooks. This
                              provides the fastest data freshness with minimal sync overhead.
                          </p>
                          {isNewSource && (
                              <LemonBanner type="info" className="mt-2">
                                  The webhook will be configured in the next step.
                              </LemonBanner>
                          )}
                      </div>
                  ),
              },
          ]
        : []

    // Webhook-only schemas (e.g. Stripe Discount) have no API list endpoint, so the
    // incremental / append / cdc / full_refresh options would all produce empty syncs.
    const hideNonWebhookOptions = !!schema.webhook_only

    // These methods merge changes into the synced table on its primary key, so they share the key and
    // output table settings below the options.
    const keyedOptions: SyncMethodOption[] = []
    if (!hideNonWebhookOptions && (canPickCdc || sourceSupportsCdc)) {
        keyedOptions.push({
            value: 'cdc',
            disabledReason: (cdcSyncSupported.disabled && cdcSyncSupported.disabledReason) || undefined,
            label: (
                <div className="mb-4 font-normal">
                    <div className="items-center flex leading-[normal] overflow-hidden mb-1">
                        <h4 className="mb-0 mr-2 text-base font-semibold">CDC (change data capture)</h4>
                        {canPickCdc && !schema.supports_webhooks && <LemonTag type="success">Recommended</LemonTag>}
                    </div>
                    <p className="mb-2">
                        Streams inserts, updates, and deletes through logical replication. Changes are captured all the
                        time and loaded into this table on its sync schedule, every 5 minutes by default. Requires a
                        primary key on the source table.
                    </p>
                    {cdcSyncSupported.disabled && (
                        <p className="mb-2 font-semibold">
                            {!isCdcOnForSource && sourceConfigurationUrl ? (
                                <>
                                    {CDC_OFF_FOR_SOURCE_REASON}, on its{' '}
                                    <Link to={sourceConfigurationUrl}>Configuration tab</Link>.
                                </>
                            ) : (
                                <>{cdcSyncSupported.disabledReason}.</>
                            )}
                        </p>
                    )}
                </div>
            ),
        })
    }
    if (shouldOfferXmin(schema)) {
        keyedOptions.push({
            value: 'xmin',
            label: (
                <div className="mb-4 font-normal">
                    <div className="items-center flex leading-[normal] overflow-hidden mb-1">
                        <h4 className="mb-0 mr-2 text-base font-semibold">xmin replication</h4>
                    </div>
                    <p className="mb-2">
                        Incremental replication using Postgres' internal <code>xmin</code> system column to track
                        changed rows — no <code>updated_at</code> column required. Each sync reads only rows inserted or
                        updated since the last run. Requires a primary key on the source table.
                    </p>
                    <p className="mb-2">
                        Does not capture row deletes, and reads the full table on every sync (the <code>xmin</code>{' '}
                        column is unindexed). {isCdcOnForSource ? 'Choose CDC' : 'Turn on CDC for this source'} if you
                        need deletes or have a very large, high-churn table.
                    </p>
                </div>
            ),
        })
    }
    if (!hideNonWebhookOptions) {
        keyedOptions.push({
            value: 'incremental',
            disabledReason: (incrementalSyncSupported.disabled && incrementalSyncSupported.disabledReason) || undefined,
            label: (
                <div className="mb-4 font-normal">
                    <div className="items-center flex leading-[normal] overflow-hidden mb-1">
                        <h4 className="mb-0 mr-2 text-base font-semibold">Incremental replication</h4>
                        {!incrementalSyncSupported.disabled && !schema.supports_webhooks && !canPickCdc && (
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
                                onChange={(newValue) => {
                                    setIncrementalFieldValue(newValue)
                                    setRadioValue('incremental')
                                }}
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
                            {radioValue === 'incremental' &&
                                incrementalFieldValue &&
                                schema.incremental_fields.find((n) => n.field === incrementalFieldValue)?.is_indexed ===
                                    false && (
                                    <LemonBanner type="warning" className="mt-2">
                                        No index detected on <code>{incrementalFieldValue}</code>. Incremental syncs
                                        query this column on every run; without an index the source database may scan
                                        the full table on each sync. Consider adding an index, or pick a different
                                        incremental field.
                                    </LemonBanner>
                                )}
                            {radioValue === 'incremental' &&
                                incrementalFieldValue &&
                                isLookbackEligibleType(
                                    schema.incremental_fields.find((n) => n.field === incrementalFieldValue)?.field_type
                                ) && (
                                    <div className="mt-4">
                                        <p className="mb-1 font-semibold">Lookback window (optional)</p>
                                        <p className="mb-2 text-secondary text-sm">
                                            On each sync, re-read rows from this far before the last synced value of{' '}
                                            <code>{incrementalFieldValue}</code>. Catches rows that arrive late or with
                                            a backdated value. The stored sync position isn't changed.
                                        </p>
                                        <div className="flex items-center gap-2">
                                            <LemonInput
                                                type="number"
                                                min={0}
                                                max={60}
                                                value={lookbackAmount ?? undefined}
                                                onChange={(newValue) => setLookbackAmount(newValue ?? null)}
                                                placeholder="0"
                                                className="w-24"
                                            />
                                            <LemonSelect
                                                value={lookbackUnit}
                                                onChange={(newValue) => setLookbackUnit(newValue)}
                                                options={[
                                                    { value: 'minutes', label: 'minutes' },
                                                    { value: 'hours', label: 'hours' },
                                                    { value: 'days', label: 'days' },
                                                ]}
                                            />
                                        </div>
                                        {lookbackSeconds !== null && lookbackSeconds > 604800 && (
                                            <LemonBanner type="warning" className="mt-2">
                                                Large lookback windows re-read more source data on every sync, which
                                                increases warehouse cost and sync duration. Consider a shorter window if
                                                your source timestamps are broadly reliable.
                                            </LemonBanner>
                                        )}
                                    </div>
                                )}
                        </>
                    )}
                </div>
            ),
        })
    }

    const appendOptions: SyncMethodOption[] = hideNonWebhookOptions
        ? []
        : [
              {
                  value: 'append',
                  disabledReason: (appendSyncSupported.disabled && appendSyncSupported.disabledReason) || undefined,
                  label: (
                      <div className="mb-4 font-normal">
                          <div className="items-center flex leading-[normal] overflow-hidden mb-1">
                              <h4 className="mb-0 mr-2 text-base font-semibold">Append only replication</h4>
                          </div>
                          <p className="mb-2">
                              When using append only replication, similar to incremental above, we'll store the max
                              value of the below field on each sync and only sync rows with greater or equal value on
                              the next run. But unlike incremental replication, we'll append the rows as opposed to
                              merge them into the existing table, meaning you can have duplicate data if the value for
                              the below field changes on a row. You should only use append only replication for sources
                              that don't support incremental.
                          </p>
                          <p className="mb-2">
                              You should pick a field that doesn't change each time the row is updated, such as a{' '}
                              <code>created_at</code> timestamp.
                          </p>
                          {!appendSyncSupported.disabled && (
                              <>
                                  <LemonSelect
                                      value={appendFieldValue}
                                      onChange={(newValue) => {
                                          setAppendFieldValue(newValue)
                                          setRadioValue('append')
                                      }}
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
                                              This field is nullable. Any rows where <code>{appendFieldValue}</code> is
                                              null will not be synced.
                                          </LemonBanner>
                                      )}
                                  {radioValue === 'append' &&
                                      appendFieldValue &&
                                      schema.incremental_fields.find((n) => n.field === appendFieldValue)
                                          ?.is_indexed === false && (
                                          <LemonBanner type="warning" className="mt-2">
                                              No index detected on <code>{appendFieldValue}</code>. Append only syncs
                                              query this column on every run; without an index the source database may
                                              scan the full table on each sync. Consider adding an index, or pick a
                                              different field.
                                          </LemonBanner>
                                      )}
                              </>
                          )}
                      </div>
                  ),
              },
          ]
    const fullRefreshOptions: SyncMethodOption[] = hideNonWebhookOptions
        ? []
        : [
              {
                  value: 'full_refresh',
                  label: (
                      <div className="mb-6 font-normal">
                          <div className="items-center flex leading-[normal] overflow-hidden mb-1">
                              <h4 className="mb-0 mr-2 text-base font-semibold">Full table replication</h4>
                          </div>
                          <p className="m-0">
                              We'll replicate the whole table on every sync. This can take longer to sync and increase
                              your monthly billing.
                          </p>
                      </div>
                  ),
              },
          ]

    const primaryKeySection =
        radioValue === 'incremental'
            ? !incrementalSyncSupported.disabled && primaryKeyPicker
            : (radioValue === 'cdc' || radioValue === 'xmin') && replicationKeyRequired && sourcePrimaryKeyNote
    const showsOutputTables =
        radioValue === 'cdc' ||
        (radioValue === 'incremental' && !incrementalSyncSupported.disabled && !!schema.incremental_history_available)
    const outputTableMode = radioValue === 'cdc' ? cdcTableMode : incrementalTableMode
    // CDC always records every change. An incremental sync can only date a version by a cursor that holds a time.
    const historyDisabledReason =
        radioValue === 'incremental' && !historyAvailable
            ? 'Choose an incremental field that holds a date and time'
            : undefined
    const keyedSettings =
        keyedOptions.some((option) => option.value === radioValue) && (primaryKeySection || showsOutputTables) ? (
            <div className="flex flex-col gap-4">
                {primaryKeySection && (
                    <div>
                        <p className="mb-1 font-semibold">Primary key</p>
                        {primaryKeySection}
                    </div>
                )}
                {showsOutputTables && (
                    <div>
                        <p className="mb-2 font-semibold">Output tables</p>
                        <LemonRadio
                            radioPosition="top"
                            value={outputTableMode}
                            onChange={(newValue) => setCdcTableMode(newValue)}
                            options={[
                                {
                                    value: 'consolidated',
                                    label: (
                                        <div className="font-normal mb-2">
                                            <div className="font-semibold">Consolidated table only</div>
                                            <p className="m-0 text-secondary text-sm">
                                                Stores the latest version of each row.
                                            </p>
                                        </div>
                                    ),
                                },
                                {
                                    value: 'cdc_only',
                                    disabledReason: historyDisabledReason,
                                    label: (
                                        <div className="font-normal mb-2">
                                            <div className="font-semibold">History table only</div>
                                            <p className="m-0 text-secondary text-sm">
                                                Stores every version of each row, with the time each version was valid.
                                            </p>
                                        </div>
                                    ),
                                },
                                {
                                    value: 'both',
                                    disabledReason: historyDisabledReason,
                                    label: (
                                        <div className="font-normal mb-2">
                                            <div className="font-semibold">Both</div>
                                            <p className="m-0 text-secondary text-sm">
                                                Stores the consolidated table and a history table.
                                            </p>
                                        </div>
                                    ),
                                },
                            ]}
                        />
                        {radioValue === 'incremental' && incrementalTableMode !== 'consolidated' && (
                            <LemonBanner type="info" className="mt-2">
                                <p className="m-0">
                                    A sync saves a new version when it sees a new value of{' '}
                                    <code>{incrementalFieldValue}</code>. Changes between two syncs become one version.
                                </p>
                                <p className="m-0">Deleted rows are not recorded.</p>
                                <p className="m-0">The history table grows with every change.</p>
                            </LemonBanner>
                        )}
                    </div>
                )}
            </div>
        ) : null

    // The form is "dirty" if the user has deviated from the server-persisted sync config. For a
    // schema that has never been set up (`schema.sync_type` is null), any selection counts as
    // dirty — the form's initial `radioValue` comes from the supported-modes default, which never
    // equals null. For an existing schema we compare each relevant field against the schema.
    const isDirty = ((): boolean => {
        if (radioValue !== schema.sync_type) {
            return true
        }
        if (radioValue === 'incremental' || radioValue === 'cdc' || radioValue === 'xmin') {
            const formPrimaryKeys = radioValue === 'incremental' ? primaryKeyColumns : (sourcePrimaryKeys ?? [])
            const serverPrimaryKeys = schema.primary_key_columns ?? []
            if (formPrimaryKeys.length !== serverPrimaryKeys.length) {
                return true
            }
            if (formPrimaryKeys.some((pk, index) => pk !== serverPrimaryKeys[index])) {
                return true
            }
        }
        if (radioValue === 'incremental') {
            if (incrementalFieldValue !== (schema.incremental_field ?? null)) {
                return true
            }
            if (lookbackSeconds !== (schema.incremental_field_lookback_seconds ?? null)) {
                return true
            }
            if (
                schema.incremental_history_available &&
                incrementalTableMode !== (schema.cdc_table_mode ?? 'consolidated')
            ) {
                return true
            }
        }
        if (radioValue === 'append' && appendFieldValue !== (schema.incremental_field ?? null)) {
            return true
        }
        if (radioValue === 'cdc' && cdcTableMode !== (schema.cdc_table_mode ?? 'consolidated')) {
            return true
        }
        return false
    })()

    const validationDisabledReason =
        lockedPrimaryKeyMismatchReason ??
        getSaveDisabledReason(
            radioValue,
            incrementalFieldValue,
            appendFieldValue,
            radioValue === 'cdc' || radioValue === 'xmin'
                ? sourcePrimaryKeys
                : primaryKeyColumns.length
                  ? primaryKeyColumns
                  : resolvedDetectedPks,
            keyRequired,
            replicationKeyRequired
        )
    const saveDisabledReason = validationDisabledReason ?? (!isDirty ? 'No changes to save' : undefined)

    const handleSave = (): void => {
        if (radioValue === 'webhook') {
            onSave('webhook', null, null, null)
        } else if (radioValue === 'cdc') {
            onSave('cdc', null, null, sourcePrimaryKeys, cdcTableMode)
        } else if (radioValue === 'xmin') {
            // xmin carries no user-picked incremental field; the source projects the system column.
            onSave('xmin', null, null, sourcePrimaryKeys)
        } else if (radioValue === 'incremental') {
            const fieldSelected = schema.incremental_fields.find((n) => n.field === incrementalFieldValue)
            if (!fieldSelected) {
                lemonToast.error('Selected field for incremental replication not found')
                return
            }

            onSave(
                'incremental',
                incrementalFieldValue,
                fieldSelected.field_type,
                primaryKeyColumns.length > 0 ? primaryKeyColumns : null,
                schema.incremental_history_available ? incrementalTableMode : undefined,
                isLookbackEligibleType(fieldSelected.field_type) ? lookbackSeconds : null
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
    }

    // The methods render as separate groups for layout, so they share one native name to stay a single
    // radio group for the keyboard and screen readers.
    const syncMethodGroupName = useId()
    const renderMethodGroup = (options: SyncMethodOption[]): JSX.Element => (
        <LemonRadio
            radioPosition="top"
            name={syncMethodGroupName}
            aria-label="Sync method"
            value={radioValue}
            options={options}
            onChange={setRadioValue}
        />
    )

    useImperativeHandle(ref, () => ({ triggerSave: handleSave }))

    useEffect(() => {
        onSaveDisabledReasonChange?.(saveDisabledReason)
    }, [saveDisabledReason, onSaveDisabledReasonChange])

    return (
        <>
            {webhookOptions.length > 0 && renderMethodGroup(webhookOptions)}
            {keyedOptions.length > 0 && (
                <div className="mb-4 rounded border p-3">
                    <p className="mb-3 text-secondary text-sm">
                        Keeps rows up to date by merging changes into the synced table on its primary key.
                    </p>
                    {renderMethodGroup(keyedOptions)}
                    {keyedSettings}
                </div>
            )}
            {appendOptions.length > 0 && renderMethodGroup(appendOptions)}
            {fullRefreshOptions.length > 0 && (
                <>
                    <LemonDivider className="mb-4" />
                    {renderMethodGroup(fullRefreshOptions)}
                </>
            )}
            {!hideFooter && (
                <div className="flex flex-row justify-end w-full">
                    <LemonButton className="mr-3" type="secondary" onClick={onClose}>
                        Close
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={saveButtonIsLoading}
                        disabledReason={saveDisabledReason}
                        onClick={handleSave}
                    >
                        Save
                    </LemonButton>
                </div>
            )}
        </>
    )
})
