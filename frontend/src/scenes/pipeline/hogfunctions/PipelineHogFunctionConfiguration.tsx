import { IconInfo } from '@posthog/icons'
import {
    LemonButton,
    LemonDropdown,
    LemonInput,
    LemonSwitch,
    LemonTextArea,
    Link,
    SpinnerOverlay,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { HogQueryEditor } from 'scenes/debug/HogDebug'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { groupsModel } from '~/models/groupsModel'
import { NodeKind } from '~/queries/schema'
import { EntityTypes } from '~/types'

import { HogFunctionIconEditable } from './HogFunctionIcon'
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
    const { isConfigurationSubmitting, configurationChanged, showSource, configuration, loading, loaded, hogFunction } =
        useValues(logic)
    const { submitConfiguration, resetForm, setShowSource, duplicate, resetToTemplate, duplicateFromTemplate } = useActions(logic)

    const hogFunctionsEnabled = !!useFeatureFlag('HOG_FUNCTIONS')
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    if (loading && !loaded) {
        return <SpinnerOverlay />
    }

    if (!loaded) {
        return <NotFound object="Hog function" />
    }

    if (!hogFunctionsEnabled && !id) {
        return (
            <div className="space-y-3">
                <div className="border rounded text-center p-4">
                    <h2>Feature not enabled</h2>
                    <p>Hog functions are not enabled for you yet. If you think they should be, contact support.</p>
                </div>
            </div>
        )
    }

    const headerButtons = (
        <>
            {!templateId && (
                <LemonButton type="secondary" onClick={() => duplicate()}>
                    Duplicate
                </LemonButton>
            )}
        </>
    )

    const saveButtons = (
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
            <PageHeader
                buttons={
                    <>
                        {headerButtons}
                        {saveButtons}
                    </>
                }
            />

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
                                <LemonField name="icon_url">
                                    {({ value, onChange }) => (
                                        <HogFunctionIconEditable
                                            logicKey={id ?? templateId ?? 'new'}
                                            search={configuration.name}
                                            src={value}
                                            onChange={(val) => onChange(val)}
                                        />
                                    )}
                                </LemonField>

                                <div className="flex flex-col py-1 flex-1">
                                    <span className="font-semibold">{configuration.name}</span>
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

                            {hogFunction?.template ? (
                                <p className="border border-dashed rounded text-muted-alt p-2">
                                    Built from template:{' '}
                                    <LemonDropdown
                                        showArrow
                                        overlay={
                                            <div className="max-w-120 p-1">
                                                <p>
                                                    This function was built from the template{' '}
                                                    <b>{hogFunction.template.name}</b>. If the template is updated, this
                                                    function is not affected unless you choose to update it.
                                                </p>

                                                <div className="flex flex-1 items-center border-t pt-2">
                                                    <div className="flex-1">
                                                        <LemonButton>Close</LemonButton>
                                                    </div>
                                                    <LemonButton onClick={() => resetToTemplate(true)}>
                                                        Reset to template
                                                    </LemonButton>

                                                    <LemonButton type="secondary" onClick={() => duplicateFromTemplate(true)}>
                                                        New function from template
                                                    </LemonButton>
                                                </div>
                                            </div>
                                        }
                                    >
                                        <Link subtle className="font-semibold">
                                            {hogFunction?.template.name} <IconInfo />
                                        </Link>
                                    </LemonDropdown>
                                </p>
                            ) : null}
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
                                                TaxonomicFilterGroupType.HogQLExpression,
                                                ...groupsTaxonomicTypes,
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
                        <div className="flex gap-2 justify-end">{saveButtons}</div>
                    </div>
                </div>
            </Form>
        </div>
    )
}
