import { LemonBanner } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { DataWarehouseSavedQueryIncrementalCheck } from '~/types'

export const LOOKBACK_OPTIONS = [
    { value: 0, label: 'No lookback' },
    { value: 60 * 60, label: '1 hour' },
    { value: 60 * 60 * 24, label: '1 day' },
    { value: 60 * 60 * 24 * 7, label: '7 days' },
]

type RefreshMode = 'full_refresh' | 'incremental'

const REFRESH_MODE_OPTIONS: LemonRadioOption<RefreshMode>[] = [
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

const INCREMENTAL_KEY_HELP =
    "A column whose value grows as rows arrive, like a timestamp or an ID. Each run reads only rows at or after the last run's highest value."
const UNIQUE_KEY_HELP =
    'Rows that match on these columns are updated in place. Include every column the query groups by. Values here can never be empty.'
const LOOKBACK_HELP =
    "How far back before the last run's highest value to read again, so rows that arrive late are picked up."

interface IncrementalConfigFieldsProps {
    /** Result of the backend eligibility check for the query being saved. */
    check: DataWarehouseSavedQueryIncrementalCheck | null
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

function IncrementalKeyInput({
    candidates,
    value,
    onChange,
    dataAttr,
}: {
    candidates: string[]
    value: string | null
    onChange: (value: string | null) => void
    dataAttr: string
}): JSX.Element {
    return (
        <LemonSelect
            value={value}
            onChange={onChange}
            options={candidates.map((column) => ({ value: column, label: column }))}
            placeholder="Select a column"
            data-attr={dataAttr}
            fullWidth
        />
    )
}

function UniqueKeyInput({
    candidates,
    value,
    onChange,
    dataAttr,
}: {
    candidates: string[]
    value: string[]
    onChange: (value: string[]) => void
    dataAttr: string
}): JSX.Element {
    return (
        <LemonInputSelect
            mode="multiple"
            value={value}
            onChange={onChange}
            options={candidates.map((column) => ({ key: column, label: column }))}
            placeholder="Select one or more columns"
            data-attr={dataAttr}
        />
    )
}

function LookbackInput({ value, onChange }: { value: number; onChange: (value: number) => void }): JSX.Element {
    return <LemonSelect value={value} onChange={onChange} options={LOOKBACK_OPTIONS} fullWidth />
}

interface IncrementalConfigOptionsProps {
    /** Result of the backend eligibility check for the view's query. Nothing renders until it arrives. */
    check: DataWarehouseSavedQueryIncrementalCheck | null
    draft: IncrementalConfigDraft
    onChange: (draft: Partial<IncrementalConfigDraft>) => void
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
    if (!check) {
        return null
    }

    if (!check.eligible || check.key_candidates.length === 0) {
        return <IneligibleBanner check={check} />
    }

    return (
        <div className="mt-2 deprecated-space-y-2">
            <RefreshModeRadio
                incremental={draft.enabled}
                onChange={(enabled) => onChange({ enabled })}
                dataAttr="materialization-refresh-mode"
            />
            {draft.enabled && (
                <div className="deprecated-space-y-2">
                    <LemonField.Pure label="Track new rows by" help={INCREMENTAL_KEY_HELP}>
                        <IncrementalKeyInput
                            candidates={check.key_candidates}
                            value={draft.incrementalKey}
                            onChange={(incrementalKey) => onChange({ incrementalKey })}
                            dataAttr="materialization-incremental-key"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Columns that identify a row" help={UNIQUE_KEY_HELP}>
                        <UniqueKeyInput
                            candidates={check.key_candidates}
                            value={draft.uniqueKey}
                            onChange={(uniqueKey) => onChange({ uniqueKey })}
                            dataAttr="materialization-incremental-unique-key"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Re-read recent data" help={LOOKBACK_HELP}>
                        <LookbackInput
                            value={draft.lookbackSeconds}
                            onChange={(lookbackSeconds) => onChange({ lookbackSeconds })}
                        />
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
export function IncrementalConfigFields({ check }: IncrementalConfigFieldsProps): JSX.Element | null {
    if (!check) {
        return null
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
                        <div className="mt-2 deprecated-space-y-2">
                            <LemonField name="incrementalKey" label="Track new rows by" help={INCREMENTAL_KEY_HELP}>
                                {({ value: key, onChange: onKeyChange }) => (
                                    <IncrementalKeyInput
                                        candidates={check.key_candidates}
                                        value={key}
                                        onChange={onKeyChange}
                                        dataAttr="sql-editor-input-save-view-incremental-key"
                                    />
                                )}
                            </LemonField>
                            <LemonField
                                name="incrementalUniqueKey"
                                label="Columns that identify a row"
                                help={UNIQUE_KEY_HELP}
                            >
                                {({ value: uniqueKey, onChange: onUniqueKeyChange }) => (
                                    <UniqueKeyInput
                                        candidates={check.key_candidates}
                                        value={uniqueKey}
                                        onChange={onUniqueKeyChange}
                                        dataAttr="sql-editor-input-save-view-incremental-unique-key"
                                    />
                                )}
                            </LemonField>
                            <LemonField
                                name="incrementalLookbackSeconds"
                                label="Re-read recent data"
                                help={LOOKBACK_HELP}
                            >
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
