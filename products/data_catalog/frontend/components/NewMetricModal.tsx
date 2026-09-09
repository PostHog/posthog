import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { METRIC_FIELD_COPY, validateMetricDescription, validateMetricName } from '../common'
import { metricsLogic, NewMetricDefinitionType } from '../metricsLogic'

const DEFINITION_TYPE_OPTIONS: { value: NewMetricDefinitionType; label: string }[] = [
    { value: 'sql', label: 'SQL' },
    { value: 'insight', label: 'Insight' },
    { value: 'markdown', label: 'Markdown' },
]

export function NewMetricModal(): JSX.Element {
    const { newMetricModalOpen, newMetricForm, isCreatingMetric, savedInsights, savedInsightsLoading } =
        useValues(metricsLogic)
    const { setNewMetricForm, createMetric, closeNewMetricModal, openSqlEditorForNewMetric, setInsightSearch } =
        useActions(metricsLogic)

    const nameError = validateMetricName(newMetricForm.name.trim())
    const descriptionError = validateMetricDescription(newMetricForm.description)
    const submitDisabledReason = nameError
        ? nameError
        : !newMetricForm.description.trim()
          ? 'Add a description'
          : descriptionError
            ? descriptionError
            : newMetricForm.definitionType === 'sql'
              ? 'Create SQL metrics from the SQL editor'
              : newMetricForm.definitionType === 'insight' && !newMetricForm.sourceInsightShortId
                ? 'Choose an insight'
                : undefined

    return (
        <LemonModal isOpen={newMetricModalOpen} onClose={closeNewMetricModal} width={640} title="New metric">
            <LemonModal.Content>
                <div className="flex flex-col gap-4">
                    <LemonField.Pure
                        label={METRIC_FIELD_COPY.name.label}
                        error={newMetricForm.name.trim() ? nameError : undefined}
                        info="A unique identifier for the metric, like monthly_active_users."
                    >
                        <LemonInput
                            value={newMetricForm.name}
                            onChange={(name) => setNewMetricForm({ name })}
                            placeholder={METRIC_FIELD_COPY.name.placeholder}
                            autoFocus
                        />
                    </LemonField.Pure>

                    <LemonField.Pure
                        label={METRIC_FIELD_COPY.displayName.label}
                        info="A human-friendly name shown in the catalog."
                    >
                        <LemonInput
                            value={newMetricForm.display_name}
                            onChange={(display_name) => setNewMetricForm({ display_name })}
                            placeholder={METRIC_FIELD_COPY.displayName.placeholder}
                        />
                    </LemonField.Pure>

                    <LemonField.Pure
                        label={METRIC_FIELD_COPY.description.label}
                        error={descriptionError}
                        info="1-3 sentences: what the metric means and what it serves."
                    >
                        <LemonTextArea
                            value={newMetricForm.description}
                            onChange={(description) => setNewMetricForm({ description })}
                            placeholder={METRIC_FIELD_COPY.description.placeholder}
                            minRows={2}
                        />
                    </LemonField.Pure>

                    <LemonField.Pure
                        label={METRIC_FIELD_COPY.unit.label}
                        info="How the result is measured, like users, dollars, or percent."
                    >
                        <LemonInput
                            value={newMetricForm.unit}
                            onChange={(unit) => setNewMetricForm({ unit })}
                            placeholder={METRIC_FIELD_COPY.unit.placeholder}
                        />
                    </LemonField.Pure>

                    <LemonField.Pure label="Definition">
                        <LemonSegmentedButton
                            value={newMetricForm.definitionType}
                            onChange={(definitionType) => setNewMetricForm({ definitionType })}
                            options={DEFINITION_TYPE_OPTIONS}
                        />
                    </LemonField.Pure>

                    {newMetricForm.definitionType === 'markdown' && (
                        <LemonBanner type="info" hideIcon>
                            You'll write the definition on the metric page after creating it.
                        </LemonBanner>
                    )}

                    {newMetricForm.definitionType === 'sql' && (
                        <LemonBanner type="info" hideIcon>
                            <div className="flex flex-col items-start gap-2">
                                <span>Write the query in the SQL editor, then use Save as metric to define it.</span>
                                <LemonButton
                                    type="secondary"
                                    onClick={openSqlEditorForNewMetric}
                                    data-attr="data-catalog-new-metric-open-sql-editor"
                                >
                                    Open SQL editor
                                </LemonButton>
                            </div>
                        </LemonBanner>
                    )}

                    {newMetricForm.definitionType === 'insight' && (
                        <LemonField.Pure
                            label="Insight"
                            info="The metric snapshots the insight's query and tracks drift against it."
                        >
                            <LemonInputSelect
                                mode="single"
                                value={newMetricForm.sourceInsightShortId ? [newMetricForm.sourceInsightShortId] : []}
                                onChange={(values) => setNewMetricForm({ sourceInsightShortId: values[0] || '' })}
                                options={savedInsights.map((insight) => ({
                                    key: insight.short_id,
                                    label: insight.label,
                                }))}
                                loading={savedInsightsLoading}
                                onInputChange={setInsightSearch}
                                placeholder="Search insights"
                                data-attr="data-catalog-new-metric-insight"
                            />
                        </LemonField.Pure>
                    )}
                </div>
            </LemonModal.Content>

            <LemonModal.Footer>
                <LemonButton type="secondary" onClick={closeNewMetricModal} disabled={isCreatingMetric}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    onClick={createMetric}
                    loading={isCreatingMetric}
                    disabledReason={submitDisabledReason}
                    data-attr="data-catalog-create-metric-submit"
                >
                    Create metric
                </LemonButton>
            </LemonModal.Footer>
        </LemonModal>
    )
}
