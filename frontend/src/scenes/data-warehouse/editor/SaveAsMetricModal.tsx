import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import {
    METRIC_DESCRIPTION_MAX_LENGTH,
    METRIC_FIELD_COPY,
    sqlNameFromDisplayName,
    validateMetricDescription,
    validateMetricName,
} from 'products/data_catalog/frontend/common'
import { MetricNameField } from 'products/data_catalog/frontend/components/MetricNameField'
import { metricsLogic } from 'products/data_catalog/frontend/metricsLogic'

import { SaveTargetCycler } from './SaveTargetCycler'
import { SaveAsMetricFields, sqlEditorLogic } from './sqlEditorLogic'

const EMPTY_FIELDS: SaveAsMetricFields = { name: '', display_name: '', description: '', unit: '' }

function trimmedFields(fields: SaveAsMetricFields): SaveAsMetricFields {
    return {
        name: fields.name.trim(),
        display_name: fields.display_name.trim(),
        description: fields.description.trim(),
        unit: fields.unit.trim(),
    }
}

export function SaveAsMetricModal(): JSX.Element {
    const { saveAsMetricModal, savingMetricAs } = useValues(sqlEditorLogic)
    const { closeSaveAsMetricModal, saveAsMetricSubmit } = useActions(sqlEditorLogic)
    const { allMetrics } = useValues(metricsLogic)
    const [fields, setFields] = useState<SaveAsMetricFields>(EMPTY_FIELDS)
    const [query, setQuery] = useState('')
    const [showErrors, setShowErrors] = useState(false)

    useEffect(() => {
        if (!saveAsMetricModal) {
            return
        }
        const { prefill, candidates } = saveAsMetricModal
        const displayName = prefill.display_name ?? ''
        setFields({
            ...EMPTY_FIELDS,
            ...prefill,
            display_name: displayName,
            name: prefill.name ?? sqlNameFromDisplayName(displayName),
        })
        setQuery(candidates.queries[candidates.initialIndex])
        setShowErrors(false)
    }, [saveAsMetricModal])

    const trimmed = trimmedFields(fields)
    const errors = {
        display_name: !trimmed.display_name ? 'Name the metric' : undefined,
        name: trimmed.display_name ? validateMetricName(trimmed.name) : undefined,
        description: !trimmed.description ? 'Add a description' : validateMetricDescription(trimmed.description),
    }
    const selectionProblem = saveAsMetricModal?.selectionProblem ?? undefined
    const hasErrors = !!(errors.display_name || errors.name || errors.description || selectionProblem)
    const sqlNameTaken = !!trimmed.name && allMetrics.some((metric) => metric.name === trimmed.name)

    const submit = (approve: boolean): void => {
        setShowErrors(true)
        if (!hasErrors) {
            saveAsMetricSubmit(trimmed, query, false, approve)
        }
    }

    return (
        <LemonModal
            isOpen={!!saveAsMetricModal}
            onClose={closeSaveAsMetricModal}
            title="Save as metric"
            width={560}
            footer={
                <div className="flex flex-wrap justify-end gap-2">
                    <LemonButton
                        type="tertiary"
                        onClick={closeSaveAsMetricModal}
                        disabledReason={savingMetricAs ? 'Saving the metric' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        onClick={() => submit(false)}
                        loading={savingMetricAs === 'propose'}
                        disabledReason={savingMetricAs === 'approve' ? 'Saving the metric' : undefined}
                        data-attr="sql-editor-save-metric-proposed"
                    >
                        Save as proposed
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => submit(true)}
                        loading={savingMetricAs === 'approve'}
                        disabledReason={savingMetricAs === 'propose' ? 'Saving the metric' : undefined}
                        data-attr="sql-editor-save-metric-approve"
                    >
                        Create and approve
                    </LemonButton>
                </div>
            }
        >
            {saveAsMetricModal && (
                <div className="flex flex-col gap-4">
                    <LemonField.Pure error={showErrors ? selectionProblem : undefined}>
                        <SaveTargetCycler
                            candidates={saveAsMetricModal.candidates}
                            onChange={(selectedQuery) => setQuery(selectedQuery)}
                        />
                    </LemonField.Pure>
                    <MetricNameField
                        displayName={fields.display_name}
                        sqlName={fields.name}
                        onChange={(name) => setFields((current) => ({ ...current, ...name }))}
                        displayNameError={showErrors ? errors.display_name : undefined}
                        sqlNameError={showErrors ? errors.name : undefined}
                        sqlNameTaken={sqlNameTaken}
                        autoFocus
                    />
                    <LemonField.Pure
                        label={METRIC_FIELD_COPY.description.label}
                        error={showErrors ? errors.description : undefined}
                    >
                        <LemonTextArea
                            value={fields.description}
                            onChange={(description) => setFields((current) => ({ ...current, description }))}
                            placeholder={METRIC_FIELD_COPY.description.placeholder}
                            maxLength={METRIC_DESCRIPTION_MAX_LENGTH}
                            minRows={2}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Unit (optional)" className="max-w-60">
                        <LemonInput
                            value={fields.unit}
                            onChange={(unit) => setFields((current) => ({ ...current, unit }))}
                            placeholder={METRIC_FIELD_COPY.unit.placeholder}
                        />
                    </LemonField.Pure>
                </div>
            )}
        </LemonModal>
    )
}
