import { LemonButton, LemonInput, LemonSwitch, LemonTextArea, SpinnerOverlay } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { HogQueryEditor } from 'scenes/debug/HogDebug'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { NodeKind } from '~/queries/schema'
import { EntityTypes } from '~/types'

import { HogFunctionInput } from './HogFunctionInputs'
import { HogFunctionInputsEditor } from './HogFunctionInputsEditor'
import { pipelineHogFunctionConfigurationLogic } from './pipelineHogFunctionConfigurationLogic'

export function PipelineHogFunctionConfiguration({
    templateId,
    id,
}: {
    templateId?: string
    id?: string
}): JSX.Element {
    const logicProps = { templateId, id }
    const logic = pipelineHogFunctionConfigurationLogic(logicProps)
    const { isConfigurationSubmitting, configurationChanged, showSource, configuration, loading, loaded } =
        useValues(logic)
    const { submitConfiguration, resetForm, setShowSource } = useActions(logic)

    if (loading && !loaded) {
        return <SpinnerOverlay />
    }

    if (!loaded) {
        return <NotFound object="Hog function" />
    }

    const buttons = (
        <>
            <LemonButton
                type="secondary"
                htmlType="reset"
                onClick={() => resetForm()}
                disabledReason={
                    !configurationChanged ? 'No changes' : isConfigurationSubmitting ? 'Saving in progress…' : undefined
                }
            >
                Clear changes
            </LemonButton>
            <LemonButton
                type="primary"
                htmlType="submit"
                onClick={submitConfiguration}
                loading={isConfigurationSubmitting}
            >
                {templateId ? 'Create' : 'Save'}
            </LemonButton>
        </>
    )

    return (
        <div className="space-y-3">
            <PageHeader buttons={buttons} />
            <Form
                logic={pipelineHogFunctionConfigurationLogic}
                props={logicProps}
                formKey="configuration"
                className="space-y-3"
            >
                <div className="flex flex-wrap gap-4 items-start">
                    <div className="flex flex-col gap-4 flex-1 min-w-100">
                        <div className="border bg-bg-light rounded p-3 space-y-2">
                            <div className="flex flex-row gap-2 min-h-16 items-center">
                                <span>🦔</span>
                                <div className="flex flex-col py-1 flex-1">
                                    <span>Hog Function</span>
                                </div>

                                <LemonField name="enabled">
                                    {({ value, onChange }) => (
                                        <LemonSwitch
                                            label="Enabled"
                                            onChange={() => onChange(!value)}
                                            checked={value}
                                            disabled={loading}
                                            bordered
                                        />
                                    )}
                                </LemonField>
                            </div>
                            <LemonField
                                name="name"
                                label="Name"
                                info="Customising the name can be useful if multiple instances of the same type are used."
                            >
                                <LemonInput type="text" disabled={loading} />
                            </LemonField>
                            <LemonField
                                name="description"
                                label="Description"
                                info="Add a description to share context with other team members"
                            >
                                <LemonTextArea disabled={loading} />
                            </LemonField>
                        </div>

                        <div className="border bg-bg-light rounded p-3 space-y-2">
                            <LemonField name="filters" label="Filters by events and actions">
                                {({ value, onChange }) => (
                                    <>
                                        <TestAccountFilterSwitch
                                            checked={value?.filter_test_accounts ?? false}
                                            onChange={(val) => onChange({ ...value, filter_test_accounts: val })}
                                            fullWidth
                                        />
                                        <ActionFilter
                                            bordered
                                            filters={value ?? {}}
                                            setFilters={(payload) => {
                                                onChange({
                                                    ...payload,
                                                    filter_test_accounts: value?.filter_test_accounts,
                                                })
                                            }}
                                            typeKey="plugin-filters"
                                            mathAvailability={MathAvailability.None}
                                            hideRename
                                            hideDuplicate
                                            showNestedArrow={false}
                                            actionsTaxonomicGroupTypes={[
                                                TaxonomicFilterGroupType.Events,
                                                TaxonomicFilterGroupType.Actions,
                                            ]}
                                            propertiesTaxonomicGroupTypes={[
                                                TaxonomicFilterGroupType.EventProperties,
                                                TaxonomicFilterGroupType.EventFeatureFlags,
                                                TaxonomicFilterGroupType.Elements,
                                                TaxonomicFilterGroupType.PersonProperties,
                                            ]}
                                            propertyFiltersPopover
                                            addFilterDefaultOptions={{
                                                id: '$pageview',
                                                name: '$pageview',
                                                type: EntityTypes.EVENTS,
                                            }}
                                            buttonCopy="Add event filter"
                                        />
                                    </>
                                )}
                            </LemonField>

                            <p className="italic text-muted-alt">
                                This destination will be triggered if <b>any of</b> the above filters match.
                            </p>
                        </div>
                    </div>

                    <div className="flex-2 min-w-100 space-y-4">
                        <div className="border bg-bg-light rounded p-3 space-y-2">
                            <div className="flex items-center justify-between">
                                <h4 className="m-0">Function configuration</h4>

                                <LemonButton size="small" type="secondary" onClick={() => setShowSource(!showSource)}>
                                    {showSource ? 'Hide source code' : 'Show source code'}
                                </LemonButton>
                            </div>

                            {showSource ? (
                                <div className="space-y-2">
                                    <LemonField name="inputs_schema" label="Input variables">
                                        <HogFunctionInputsEditor />
                                    </LemonField>

                                    <LemonField name="hog" label="Hog code">
                                        {({ value, onChange }) => (
                                            // TODO: Fix this so we don't have to click "update and run"
                                            <HogQueryEditor
                                                query={{
                                                    kind: NodeKind.HogQuery,
                                                    code: value ?? '',
                                                }}
                                                setQuery={(q) => {
                                                    onChange(q.code)
                                                }}
                                            />
                                        )}
                                    </LemonField>
                                </div>
                            ) : (
                                <div className="space-y-2">
                                    {configuration?.inputs_schema?.length ? (
                                        configuration?.inputs_schema.map((schema) => {
                                            return (
                                                <div key={schema.key}>
                                                    <LemonField
                                                        name={`inputs.${schema.key}`}
                                                        label={schema.label || schema.key}
                                                        showOptional={!schema.required}
                                                    >
                                                        {({ value, onChange }) => {
                                                            return (
                                                                <HogFunctionInput
                                                                    schema={schema}
                                                                    value={value?.value}
                                                                    onChange={(val) => onChange({ value: val })}
                                                                />
                                                            )
                                                        }}
                                                    </LemonField>
                                                </div>
                                            )
                                        })
                                    ) : (
                                        <span className="italic text-muted-alt">
                                            This function does not require any input variables.
                                        </span>
                                    )}
                                </div>
                            )}
                        </div>
                        <div className="flex gap-2 justify-end">{buttons}</div>
                    </div>
                </div>
            </Form>
        </div>
    )
}
