import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useRef } from 'react'

import { Button, Heading, Input, Text, Textarea, ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { METRIC_DESCRIPTION_MAX_LENGTH, METRIC_FIELD_COPY } from './common'
import { MetricMarkdownEditorField } from './components/MetricMarkdownEditorField'
import { QuillMetricFormField } from './components/QuillMetricFormField'
import { QuillMetricNameField } from './components/QuillMetricNameField'
import { QuillNewMetricInsightDefinition } from './components/QuillNewMetricInsightDefinition'
import { QuillNewMetricSqlDefinition } from './components/QuillNewMetricSqlDefinition'
import { dataCatalogNewMetricSceneLogic } from './dataCatalogNewMetricSceneLogic'
import { DEFINITION_TYPE_HINTS, DEFINITION_TYPE_OPTIONS, isMetricDefinitionType } from './newMetricDefinitionTypes'

export function QuillDataCatalogNewMetricScene(): JSX.Element {
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
                    <div className="flex flex-wrap justify-end gap-2" data-quill>
                        <Button
                            variant="default"
                            render={<LinkPrimitive to={urls.dataCatalog('metrics')} />}
                            disabledReason={saving ? 'Saving the metric' : undefined}
                            data-attr="data-catalog-new-metric-cancel"
                        >
                            Cancel
                        </Button>
                        <Button
                            variant="outline"
                            onClick={() => submitMetric(false)}
                            loading={saving === 'propose'}
                            disabledReason={saving === 'approve' ? 'Saving the metric' : undefined}
                            data-attr="data-catalog-new-metric-save-proposed"
                        >
                            Save as proposed
                        </Button>
                        <Button
                            variant="primary"
                            type="submit"
                            onClick={() => submitMetric(true)}
                            loading={saving === 'approve'}
                            disabledReason={saving === 'propose' ? 'Saving the metric' : undefined}
                            data-attr="data-catalog-create-metric-submit"
                        >
                            Create and approve
                        </Button>
                    </div>
                </SceneStickyBar>
                <div className="flex max-w-3xl min-w-0 flex-col gap-8 pt-2" data-quill>
                    <QuillMetricNameField
                        displayName={metricForm.display_name}
                        sqlName={metricForm.name}
                        onChange={setMetricFormValues}
                        displayNameError={fieldError('display_name')}
                        sqlNameError={fieldError('name')}
                        sqlNameTaken={sqlNameTaken}
                        autoFocus
                    />

                    <section className="flex min-w-0 flex-col gap-2">
                        <Heading size="sm" render={<h3 className="m-0" />}>
                            How it's calculated
                        </Heading>
                        <QuillMetricFormField name="definitionType">
                            {({ value, onChange }) => (
                                <ToggleGroup
                                    variant="outline"
                                    aria-label="How it's calculated"
                                    value={[value]}
                                    onValueChange={(next: string[]) =>
                                        isMetricDefinitionType(next[0]) && onChange(next[0])
                                    }
                                >
                                    {DEFINITION_TYPE_OPTIONS.map((option) => (
                                        <ToggleGroupItem key={option.value} value={option.value}>
                                            {option.label}
                                        </ToggleGroupItem>
                                    ))}
                                </ToggleGroup>
                            )}
                        </QuillMetricFormField>
                        <Text size="xs" variant="muted" className="m-0">
                            {DEFINITION_TYPE_HINTS[metricForm.definitionType]}
                        </Text>
                        {metricForm.definitionType === 'sql' && (
                            <QuillNewMetricSqlDefinition onAddUnit={() => unitInputRef.current?.focus()} />
                        )}
                        {metricForm.definitionType === 'insight' && <QuillNewMetricInsightDefinition />}
                        {metricForm.definitionType === 'markdown' && (
                            <QuillMetricFormField name="markdown">
                                {({ value, onChange }) => (
                                    <MetricMarkdownEditorField value={value} onChange={onChange} />
                                )}
                            </QuillMetricFormField>
                        )}
                    </section>

                    <section className="flex min-w-0 flex-col gap-4">
                        <Heading size="sm" render={<h3 className="m-0" />}>
                            Details
                        </Heading>
                        <QuillMetricFormField
                            name="description"
                            label={METRIC_FIELD_COPY.description.label}
                            description="One or two short sentences: what the number is and what it counts."
                        >
                            {({ id, value, onChange, invalid }) => (
                                <Textarea
                                    id={id}
                                    value={value}
                                    onChange={(event) => onChange(event.target.value)}
                                    placeholder={METRIC_FIELD_COPY.description.placeholder}
                                    rows={2}
                                    maxLength={METRIC_DESCRIPTION_MAX_LENGTH}
                                    aria-invalid={invalid || undefined}
                                    data-attr="data-catalog-new-metric-description"
                                />
                            )}
                        </QuillMetricFormField>
                        <QuillMetricFormField name="unit" label="Unit (optional)" className="max-w-60">
                            {({ id, value, onChange }) => (
                                <Input
                                    id={id}
                                    ref={unitInputRef}
                                    value={value}
                                    onChange={(event) => onChange(event.target.value)}
                                    placeholder={METRIC_FIELD_COPY.unit.placeholder}
                                    data-attr="data-catalog-new-metric-unit"
                                />
                            )}
                        </QuillMetricFormField>
                    </section>
                </div>
            </Form>
        </SceneContent>
    )
}
