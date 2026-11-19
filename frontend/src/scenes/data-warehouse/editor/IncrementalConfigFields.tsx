import { useMountedLogic, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { ApiError } from 'lib/api-error'
import { lemonDialogLogic } from 'lib/lemon-ui/LemonDialog/lemonDialogLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

import { DataWarehouseSavedQueryIncrementalCheck } from '~/types'

import { saveViewIncrementalLogic } from 'products/data_warehouse/frontend/sql_editor/saveViewIncrementalLogic'

export const LOOKBACK_OPTIONS = [
    { value: 0, label: 'No lookback' },
    { value: 60 * 60, label: '1 hour' },
    { value: 60 * 60 * 24, label: '1 day' },
    { value: 60 * 60 * 24 * 7, label: '7 days' },
]

export type RefreshMode = 'full_refresh' | 'incremental'

export const REFRESH_MODE_OPTIONS: LemonRadioOption<RefreshMode>[] = [
    {
        value: 'full_refresh',
        label: 'Full refresh',
        description: 'Each run rebuilds the whole table from scratch.',
    },
    {
        value: 'incremental',
        label: 'Incremental',
        description: 'Each run adds or updates only rows that are new since the last run.',
    },
]

export const INCREMENTAL_KEY_LABEL = 'Incremental column'
export const INCREMENTAL_KEY_HELP =
    "The column that tracks which rows are new: its value grows as rows arrive, like a timestamp or a sequential ID. Each run reads only rows at or after the last run's highest value."
export const UNIQUE_KEY_LABEL = 'Unique key'
export const UNIQUE_KEY_HELP =
    'The columns that together identify a row, like a primary key. Rows that match on them are updated in place. Include every column the query groups by. Values here can never be empty.'
export const LOOKBACK_HELP =
    'Include this much previously processed data in each run to catch late arrivals and updates.'

/** Save-as-view form fields, keyed by the `blocked_keys` names the API reports for a refused config. */
const BLOCKED_KEY_FORM_FIELDS: Record<string, string> = {
    incremental_key: 'incrementalKey',
    unique_key: 'incrementalUniqueKey',
}

/**
 * The save-as-view form field that a refused incremental config names, with the error to show under
 * it. The error detail is the first blocker, which belongs to the first blocked key.
 */
export function incrementalFieldErrorFromSave(error: unknown): { field: string; message: string } | null {
    if (!(error instanceof ApiError) || error.status !== 400 || error.attr !== 'incremental' || !error.detail) {
        return null
    }
    const blockedKeys: unknown = error.data?.extra?.blocked_keys
    const field = Array.isArray(blockedKeys) ? BLOCKED_KEY_FORM_FIELDS[String(blockedKeys[0])] : undefined
    return field ? { field, message: error.detail } : null
}

interface IncrementalConfigFieldsProps {
    queries: string[]
}

/** What the user has picked so far, before it becomes a saved incremental config. */
export interface IncrementalConfigDraft {
    enabled: boolean
    incrementalKey: string | null
    uniqueKey: string[]
    lookbackSeconds: number
}

export const EMPTY_INCREMENTAL_DRAFT: IncrementalConfigDraft = {
    enabled: false,
    incrementalKey: null,
    uniqueKey: [],
    lookbackSeconds: 0,
}

function IneligibleBanner({ check }: { check: DataWarehouseSavedQueryIncrementalCheck }): JSX.Element {
    return (
        <LemonBanner type="info" className="mt-2">
            <span className="text-xs">
                This query is always refreshed in full.{' '}
                {check.blockers[0] ?? 'It has no column that can track which rows are new.'}
            </span>
        </LemonBanner>
    )
}

function WarningsBanner({ warnings }: { warnings: string[] }): JSX.Element | null {
    if (warnings.length === 0) {
        return null
    }
    return (
        <LemonBanner type="warning">
            <ul className="text-xs deprecated-space-y-1">
                {warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                ))}
            </ul>
        </LemonBanner>
    )
}

function RefreshModeRadio({
    incremental,
    onChange,
    dataAttr,
}: {
    incremental: boolean
    onChange: (incremental: boolean) => void
    dataAttr: string
}): JSX.Element {
    return (
        <LemonRadio
            value={incremental ? 'incremental' : 'full_refresh'}
            onChange={(mode: RefreshMode) => onChange(mode === 'incremental')}
            options={REFRESH_MODE_OPTIONS.map((option) => ({
                ...option,
                'data-attr': `${dataAttr}-${option.value}`,
            }))}
            radioPosition="top"
        />
    )
}

function ColumnWithType({ column, columnType }: { column: string; columnType?: string }): JSX.Element {
    return (
        <span className="flex items-center gap-2">
            {column}
            {columnType && <LemonTag type="muted">{columnType}</LemonTag>}
        </span>
    )
}

function IncrementalKeyInput({
    check,
    value,
    onChange,
    dataAttr,
}: {
    check: DataWarehouseSavedQueryIncrementalCheck
    value: string | null
    onChange: (value: string | null) => void
    dataAttr: string
}): JSX.Element {
    return (
        <LemonSelect
            value={value}
            onChange={onChange}
            options={check.key_candidates.map((column) => ({
                value: column,
                label: <ColumnWithType column={column} columnType={check.key_candidate_types?.[column]} />,
            }))}
            placeholder="Select a column"
            data-attr={dataAttr}
            size="small"
            renderButtonContent={(option) => option?.value ?? 'Select a column'}
            fullWidth
        />
    )
}

export function uniqueKeyCandidates(check: DataWarehouseSavedQueryIncrementalCheck): string[] {
    // Wider than key_candidates: identifying a row only needs equality, so strings qualify here
    // even though they cannot track new rows.
    return check.unique_key_candidates ?? check.key_candidates
}

function UniqueKeyInput({
    check,
    value,
    onChange,
    dataAttr,
}: {
    check: DataWarehouseSavedQueryIncrementalCheck
    value: string[]
    onChange: (value: string[]) => void
    dataAttr: string
}): JSX.Element {
    const candidates = uniqueKeyCandidates(check)
    return (
        <LemonInputSelect
            mode="multiple"
            size="small"
            fullWidth
            transparentBackground
            value={value}
            onChange={onChange}
            options={candidates.map((column) => ({
                key: column,
                label: column,
                tooltip: check.key_candidate_types?.[column],
            }))}
            placeholder="Add column"
            data-attr={dataAttr}
        />
    )
}

function LookbackInput({ value, onChange }: { value: number; onChange: (value: number) => void }): JSX.Element {
    return <LemonSelect value={value} onChange={onChange} options={LOOKBACK_OPTIONS} size="small" fullWidth />
}

interface IncrementalConfigOptionsProps {
    /** Result of the backend eligibility check for the view's query. */
    check: DataWarehouseSavedQueryIncrementalCheck | null
    draft: IncrementalConfigDraft
    onChange: (draft: Partial<IncrementalConfigDraft>) => void
}

export const INCREMENTAL_CHECK_LOADING: DataWarehouseSavedQueryIncrementalCheck = {
    eligible: false,
    key_candidates: [],
    blockers: [],
    warnings: [],
}

/**
 * Controlled version of the incremental settings, for surfaces without a kea form —
 * the materialization panel and modal.
 */
export function IncrementalConfigOptions({
    check,
    draft,
    onChange,
}: IncrementalConfigOptionsProps): JSX.Element | null {
    if (check === INCREMENTAL_CHECK_LOADING) {
        return (
            <div className="mt-4 deprecated-space-y-2" data-attr="materialization-refresh-mode-loading">
                <LemonSkeleton className="h-8 w-full" repeat={2} />
            </div>
        )
    }

    if (!check) {
        return null
    }

    if (!check.eligible || check.key_candidates.length === 0) {
        return <IneligibleBanner check={check} />
    }

    return (
        <div className="mt-4 deprecated-space-y-4">
            <RefreshModeRadio
                incremental={draft.enabled}
                onChange={(enabled) => onChange({ enabled })}
                dataAttr="materialization-refresh-mode"
            />
            {draft.enabled && (
                <div className="@container/incremental mt-4 ml-6 max-w-120 space-y-3">
                    <LemonField.Pure
                        className="@min-[400px]/incremental:flex-row @min-[400px]/incremental:items-center"
                        labelClassName="@min-[400px]/incremental:w-44 @min-[400px]/incremental:shrink-0"
                        label={INCREMENTAL_KEY_LABEL}
                        info={INCREMENTAL_KEY_HELP}
                    >
                        <div className="min-w-0 w-full flex-1">
                            <IncrementalKeyInput
                                check={check}
                                value={draft.incrementalKey}
                                onChange={(incrementalKey) => onChange({ incrementalKey })}
                                dataAttr="materialization-incremental-key"
                            />
                        </div>
                    </LemonField.Pure>
                    <LemonField.Pure
                        className="@min-[400px]/incremental:flex-row @min-[400px]/incremental:items-center"
                        labelClassName="@min-[400px]/incremental:w-44 @min-[400px]/incremental:shrink-0"
                        label={UNIQUE_KEY_LABEL}
                        info={UNIQUE_KEY_HELP}
                    >
                        <div className="min-w-0 w-full flex-1">
                            <UniqueKeyInput
                                check={check}
                                value={draft.uniqueKey}
                                onChange={(uniqueKey) => onChange({ uniqueKey })}
                                dataAttr="materialization-incremental-unique-key"
                            />
                        </div>
                    </LemonField.Pure>
                    <LemonField.Pure
                        className="@min-[400px]/incremental:flex-row @min-[400px]/incremental:items-center"
                        labelClassName="@min-[400px]/incremental:w-44 @min-[400px]/incremental:shrink-0"
                        label="Lookback window"
                        info={LOOKBACK_HELP}
                    >
                        <div className="min-w-0 w-full flex-1">
                            <LookbackInput
                                value={draft.lookbackSeconds}
                                onChange={(lookbackSeconds) => onChange({ lookbackSeconds })}
                            />
                        </div>
                    </LemonField.Pure>
                    <WarningsBanner warnings={check.warnings} />
                </div>
            )}
        </div>
    )
}

/**
 * Incremental settings inside the save-as-view form.
 *
 * Rendered only when the view is being materialized, since incremental describes how a
 * materialized table is refreshed and means nothing without one.
 */
export function IncrementalConfigFields({ queries }: IncrementalConfigFieldsProps): JSX.Element | null {
    const formLogic = useMountedLogic(lemonDialogLogic)
    const { form } = useValues(formLogic)
    const { check, checkLoading } = useValues(
        saveViewIncrementalLogic({
            query: queries[Number(form.saveTarget)] ?? '',
            dialogKey: String(formLogic.key),
            enabled: Boolean(form.materializeAfterSave),
        })
    )

    if (!form.materializeAfterSave) {
        return null
    }

    if (checkLoading) {
        return (
            <div className="mt-4 deprecated-space-y-2" data-attr="sql-editor-save-view-incremental-loading">
                <LemonSkeleton className="h-8 w-full" repeat={2} />
            </div>
        )
    }

    if (!check) {
        return (
            <LemonBanner type="info" className="mt-2">
                Incremental options are unavailable. You can still save this view with a full refresh.
            </LemonBanner>
        )
    }

    if (!check.eligible || check.key_candidates.length === 0) {
        return <IneligibleBanner check={check} />
    }

    return (
        <LemonField name="incrementalEnabled" className="mt-2">
            {({ value, onChange }) => (
                <>
                    <RefreshModeRadio
                        incremental={!!value}
                        onChange={onChange}
                        dataAttr="sql-editor-save-view-refresh-mode"
                    />
                    {value && (
                        <div className="mt-4 deprecated-space-y-4">
                            <LemonField name="incrementalKey" label={INCREMENTAL_KEY_LABEL} info={INCREMENTAL_KEY_HELP}>
                                {({ value: key, onChange: onKeyChange }) => (
                                    <IncrementalKeyInput
                                        check={check}
                                        value={key}
                                        onChange={onKeyChange}
                                        dataAttr="sql-editor-input-save-view-incremental-key"
                                    />
                                )}
                            </LemonField>
                            <LemonField name="incrementalUniqueKey" label={UNIQUE_KEY_LABEL} info={UNIQUE_KEY_HELP}>
                                {({ value: uniqueKey, onChange: onUniqueKeyChange }) => (
                                    <UniqueKeyInput
                                        check={check}
                                        value={uniqueKey}
                                        onChange={onUniqueKeyChange}
                                        dataAttr="sql-editor-input-save-view-incremental-unique-key"
                                    />
                                )}
                            </LemonField>
                            <LemonField name="incrementalLookbackSeconds" label="Lookback window" info={LOOKBACK_HELP}>
                                {({ value: lookback, onChange: onLookbackChange }) => (
                                    <LookbackInput value={lookback} onChange={onLookbackChange} />
                                )}
                            </LemonField>
                            <WarningsBanner warnings={check.warnings} />
                        </div>
                    )}
                </>
            )}
        </LemonField>
    )
}
