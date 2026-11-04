import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useRef } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { METRIC_DESCRIPTION_MAX_LENGTH, METRIC_FIELD_COPY } from './common'
import { MetricMarkdownEditorField } from './components/MetricMarkdownEditorField'
import { MetricNameField } from './components/MetricNameField'
import { NewMetricInsightDefinition } from './components/NewMetricInsightDefinition'
import { NewMetricSqlDefinition } from './components/NewMetricSqlDefinition'
import { dataCatalogNewMetricSceneLogic, MetricDefinitionType } from './dataCatalogNewMetricSceneLogic'

export const scene: SceneExport = {
    component: DataCatalogNewMetricScene,
    logic: dataCatalogNewMetricSceneLogic,
}

const DEFINITION_TYPE_OPTIONS: { value: MetricDefinitionType; label: string }[] = [
    { value: 'sql', label: 'SQL' },
    { value: 'insight', label: 'Insight' },
    { value: 'markdown', label: 'Markdown' },
]

const DEFINITION_TYPE_HINTS: Record<MetricDefinitionType, string> = {
    sql: 'Return the number. Agents and dashboards run this query.',
    insight: 'Use a saved insight. The metric copies its query.',
    markdown: 'Write the steps in words, for metrics that are not one query. Agents follow them.',
}

export function DataCatalogNewMetricScene(): JSX.Element {
    const { metricForm, metricFormValidationErrors, showMetricFormErrors, saving, sqlNameTaken } =
        useValues(dataCatalogNewMetricSceneLogic)
    const { setMetricFormValues, submitMetric } = useActions(dataCatalogNewMetricSceneLogic)
    const unitInputRef = useRef<HTMLInputElement>(null)
    const fieldError = (field: 'display_name' | 'name'): string | undefined =>
        showMetricFormErrors ? (metricFormValidationErrors[field] as string | undefined) : undefined

    return (
        <SceneContent>
            <Form logic={dataCatalogNewMetricSceneLogic} formKey="metricForm">
                <SceneTitleSection name="New metric" resourceType={{ type: 'data_warehouse' }} />
                <SceneStickyBar>
                    <div className="flex flex-wrap justify-end gap-2">
                        <LemonButton
                            type="tertiary"
                            to={urls.dataCatalog()}
                            disabledReason={saving ? 'Saving the metric' : undefined}
                            data-attr="data-catalog-new-metric-cancel"
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            onClick={() => submitMetric(false)}
                            loading={saving === 'propose'}
                            disabledReason={saving === 'approve' ? 'Saving the metric' : undefined}
                            data-attr="data-catalog-new-metric-save-proposed"
                        >
                            Save as proposed
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            onClick={() => submitMetric(true)}
                            loading={saving === 'approve'}
                            disabledReason={saving === 'propose' ? 'Saving the metric' : undefined}
                            data-attr="data-catalog-create-metric-submit"
                        >
                            Create and approve
                        </LemonButton>
                    </div>
                </SceneStickyBar>
                <div className="flex max-w-3xl flex-col gap-8 pt-2">
                    <MetricNameField
                        displayName={metricForm.display_name}
                        sqlName={metricForm.name}
                        onChange={setMetricFormValues}
                        displayNameError={fieldError('display_name')}
                        sqlNameError={fieldError('name')}
                        sqlNameTaken={sqlNameTaken}
                        autoFocus
                    />

                    <section className="flex flex-col gap-2">
                        <h3 className="m-0 text-sm font-semibold">How it's calculated</h3>
                        <LemonField name="definitionType">
                            <LemonSegmentedButton options={DEFINITION_TYPE_OPTIONS} size="small" />
                        </LemonField>
                        <p className="m-0 text-xs text-secondary">{DEFINITION_TYPE_HINTS[metricForm.definitionType]}</p>
                        {metricForm.definitionType === 'sql' && (
                            <NewMetricSqlDefinition onAddUnit={() => unitInputRef.current?.focus()} />
                        )}
                        {metricForm.definitionType === 'insight' && <NewMetricInsightDefinition />}
                        {metricForm.definitionType === 'markdown' && (
                            <LemonField name="markdown">
                                {({ value, onChange }) => (
                                    <MetricMarkdownEditorField value={value} onChange={onChange} />
                                )}
                            </LemonField>
                        )}
                    </section>

                    <section className="flex flex-col gap-4">
                        <h3 className="m-0 text-sm font-semibold">Details</h3>
                        <LemonField
                            name="description"
                            label={METRIC_FIELD_COPY.description.label}
                            help="One or two short sentences: what the number is and what it counts."
                        >
                            <LemonTextArea
                                placeholder={METRIC_FIELD_COPY.description.placeholder}
                                minRows={2}
                                maxLength={METRIC_DESCRIPTION_MAX_LENGTH}
                                data-attr="data-catalog-new-metric-description"
                            />
                        </LemonField>
                        <LemonField name="unit" label="Unit (optional)" className="max-w-60">
                            <LemonInput
                                inputRef={unitInputRef}
                                placeholder={METRIC_FIELD_COPY.unit.placeholder}
                                data-attr="data-catalog-new-metric-unit"
                            />
                        </LemonField>
                    </section>
                </div>
            </Form>
        </SceneContent>
    )
}
