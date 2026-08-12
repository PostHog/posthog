import { LemonBanner } from '@posthog/lemon-ui'

import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { DataWarehouseSavedQueryIncrementalCheck } from '~/types'

export const LOOKBACK_OPTIONS = [
    { value: 0, label: 'No lookback' },
    { value: 60 * 60, label: '1 hour' },
    { value: 60 * 60 * 24, label: '1 day' },
    { value: 60 * 60 * 24 * 7, label: '7 days' },
]

interface IncrementalConfigFieldsProps {
    /** Result of the backend eligibility check for the query being saved. */
    check: DataWarehouseSavedQueryIncrementalCheck | null
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
        return (
            <LemonBanner type="info" className="mt-2">
                <span className="text-xs">
                    This query is always refreshed in full.{' '}
                    {check.blockers[0] ?? 'It has no column that can track which rows are new.'}
                </span>
            </LemonBanner>
        )
    }

    const columnOptions = check.key_candidates.map((column) => ({ key: column, label: column }))

    return (
        <LemonField name="incrementalEnabled" className="mt-2">
            {({ value, onChange }) => (
                <>
                    <LemonCheckbox
                        checked={value}
                        onChange={onChange}
                        data-attr="sql-editor-input-save-view-incremental"
                        label="Update only new rows on each run"
                    />
                    {value && (
                        <div className="mt-2 deprecated-space-y-2">
                            <LemonField name="incrementalKey" label="Track new rows by">
                                {({ value: key, onChange: onKeyChange }) => (
                                    <LemonSelect
                                        value={key}
                                        onChange={onKeyChange}
                                        options={check.key_candidates.map((column) => ({
                                            value: column,
                                            label: column,
                                        }))}
                                        placeholder="Select a column"
                                        data-attr="sql-editor-input-save-view-incremental-key"
                                        fullWidth
                                    />
                                )}
                            </LemonField>
                            <LemonField
                                name="incrementalUniqueKey"
                                label="Columns that identify a row"
                                info="Used to match recomputed rows against stored ones. Include every column the query groups by. These columns can never be empty."
                            >
                                {({ value: uniqueKey, onChange: onUniqueKeyChange }) => (
                                    <LemonInputSelect
                                        mode="multiple"
                                        value={uniqueKey}
                                        onChange={onUniqueKeyChange}
                                        options={columnOptions}
                                        placeholder="Select one or more columns"
                                        data-attr="sql-editor-input-save-view-incremental-unique-key"
                                    />
                                )}
                            </LemonField>
                            <LemonField
                                name="incrementalLookbackSeconds"
                                label="Re-read recent data"
                                info="How far back before the last run's high point to read again, so data that arrives late is picked up."
                            >
                                {({ value: lookback, onChange: onLookbackChange }) => (
                                    <LemonSelect
                                        value={lookback}
                                        onChange={onLookbackChange}
                                        options={LOOKBACK_OPTIONS}
                                        fullWidth
                                    />
                                )}
                            </LemonField>
                            {check.warnings.length > 0 && (
                                <LemonBanner type="warning">
                                    <ul className="text-xs deprecated-space-y-1">
                                        {check.warnings.map((warning) => (
                                            <li key={warning}>{warning}</li>
                                        ))}
                                    </ul>
                                </LemonBanner>
                            )}
                        </div>
                    )}
                </>
            )}
        </LemonField>
    )
}
