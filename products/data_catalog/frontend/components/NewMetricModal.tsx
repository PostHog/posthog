import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { LemonTextAreaMarkdown } from 'lib/lemon-ui/LemonTextArea/LemonTextAreaMarkdown'

import { validateMetricName } from '../common'
import { metricsLogic, NewMetricDefinitionType } from '../metricsLogic'

// The Text (markdown) option is hidden until its editor UI is polished.
const DEFINITION_TYPE_OPTIONS: { value: NewMetricDefinitionType; label: string }[] = [
    { value: 'sql', label: 'SQL' },
    { value: 'insight', label: 'Insight' },
]

export function NewMetricModal(): JSX.Element {
    const { newMetricModalOpen, newMetricForm, isCreatingMetric, savedInsights, savedInsightsLoading } =
        useValues(metricsLogic)
    const { setNewMetricForm, createMetric, closeNewMetricModal, openSqlEditorForNewMetric, setInsightSearch } =
        useActions(metricsLogic)

    const nameError = validateMetricName(newMetricForm.name.trim())
    const submitDisabledReason = nameError
        ? nameError
        : !newMetricForm.description.trim()
          ? 'Add a description'
          : newMetricForm.definitionType === 'sql'
            ? 'Create SQL metrics from the SQL editor'
            : newMetricForm.definitionType === 'insight' && !newMetricForm.sourceInsightShortId
              ? 'Choose an insight'
              : newMetricForm.definitionType === 'markdown' && !newMetricForm.markdown.trim()
                ? 'Add the markdown definition'
                : undefined

    return (
        <LemonModal isOpen={newMetricModalOpen} onClose={closeNewMetricModal} width={640} title="New metric">
            <LemonModal.Content>
                <div className="flex flex-col gap-4">
                    <LemonField.Pure
                        label="Name"
                        error={newMetricForm.name.trim() ? nameError : undefined}
                        info="A unique identifier for the metric, like monthly_active_users."
                    >
                        <LemonInput
                            value={newMetricForm.name}
                            onChange={(name) => setNewMetricForm({ name })}
                            placeholder="monthly_active_users"
                            autoFocus
                        />
                    </LemonField.Pure>

                    <LemonField.Pure label="Display name" info="A human-friendly name shown in the catalog.">
                        <LemonInput
                            value={newMetricForm.display_name}
                            onChange={(display_name) => setNewMetricForm({ display_name })}
                            placeholder="Monthly active users"
                        />
                    </LemonField.Pure>

                    <LemonField.Pure label="Description">
                        <LemonTextArea
                            value={newMetricForm.description}
                            onChange={(description) => setNewMetricForm({ description })}
                            placeholder="What this metric measures and how to read it"
                            minRows={2}
                        />
                    </LemonField.Pure>

                    <LemonField.Pure label="Unit" info="How the result is measured, like users, dollars, or percent.">
                        <LemonInput
                            value={newMetricForm.unit}
                            onChange={(unit) => setNewMetricForm({ unit })}
                            placeholder="users"
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
                        <LemonField.Pure label="Text">
                            <LemonTextAreaMarkdown
                                value={newMetricForm.markdown}
                                onChange={(markdown) => setNewMetricForm({ markdown })}
                                placeholder="Numbered steps describing how to calculate this metric"
                            />
                        </LemonField.Pure>
                    )}

                    {newMetricForm.definitionType === 'sql' && (
                        <LemonBanner type="info">
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
