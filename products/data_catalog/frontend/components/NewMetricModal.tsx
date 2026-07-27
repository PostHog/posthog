import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { LemonTextAreaMarkdown } from 'lib/lemon-ui/LemonTextArea/LemonTextAreaMarkdown'

import { validateMetricName } from '../common'
import { metricsLogic, NewMetricDefinitionType } from '../metricsLogic'

const DEFINITION_TYPE_OPTIONS: { value: NewMetricDefinitionType; label: string }[] = [
    { value: 'none', label: 'No definition' },
    { value: 'sql', label: 'SQL' },
    { value: 'markdown', label: 'Markdown' },
]

export function NewMetricModal(): JSX.Element {
    const { newMetricModalOpen, newMetricForm, isCreatingMetric } = useValues(metricsLogic)
    const { setNewMetricForm, createMetric, closeNewMetricModal } = useActions(metricsLogic)

    const nameError = validateMetricName(newMetricForm.name.trim())
    const submitDisabledReason = nameError
        ? nameError
        : !newMetricForm.description.trim()
          ? 'Add a description'
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

                    {newMetricForm.definitionType === 'sql' && (
                        <LemonField.Pure label="SQL">
                            <LemonTextArea
                                value={newMetricForm.sql}
                                onChange={(sql) => setNewMetricForm({ sql })}
                                placeholder="SELECT count() FROM events"
                                className="font-mono"
                                minRows={4}
                            />
                        </LemonField.Pure>
                    )}

                    {newMetricForm.definitionType === 'markdown' && (
                        <LemonField.Pure label="Markdown">
                            <LemonTextAreaMarkdown
                                value={newMetricForm.markdown}
                                onChange={(markdown) => setNewMetricForm({ markdown })}
                                placeholder="Numbered steps describing how to calculate this metric"
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
