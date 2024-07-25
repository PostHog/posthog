import { IconInfo, IconPlus } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDivider,
    LemonDropdown,
    LemonInput,
    LemonLabel,
    LemonSwitch,
    LemonTextArea,
    Link,
    Spinner,
    SpinnerOverlay,
} from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { Sparkline } from 'lib/components/Sparkline'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { groupsModel } from '~/models/groupsModel'
import { AvailableFeature, EntityTypes } from '~/types'

import { hogFunctionConfigurationLogic } from './hogFunctionConfigurationLogic'
import { HogFunctionIconEditable } from './HogFunctionIcon'
import { HogFunctionInputs } from './HogFunctionInputs'
import { HogFunctionStatusIndicator } from './HogFunctionStatusIndicator'
import { HogFunctionTest, HogFunctionTestPlaceholder } from './HogFunctionTest'

const EVENT_THRESHOLD_ALERT_LEVEL = 8000

export function HogFunctionConfiguration({ templateId, id }: { templateId?: string; id?: string }): JSX.Element {
    const logicProps = { templateId, id }
    const logic = hogFunctionConfigurationLogic(logicProps)
    const {
        isConfigurationSubmitting,
        configurationChanged,
        showSource,
        configuration,
        loading,
        loaded,
        hogFunction,
        willReEnableOnSave,
        exampleInvocationGlobalsWithInputs,
        showPaygate,
        hasAddon,
        sparkline,
        sparklineLoading,
    } = useValues(logic)
    const {
        submitConfiguration,
        resetForm,
        setShowSource,
        duplicate,
        resetToTemplate,
        duplicateFromTemplate,
        setConfigurationValue,
        deleteHogFunction,
    } = useActions(logic)

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
                <>
                    <More
                        overlay={
                            <>
                                <LemonButton fullWidth onClick={() => duplicate()}>
                                    Duplicate
                                </LemonButton>
                                <LemonDivider />
                                <LemonButton status="danger" fullWidth onClick={() => deleteHogFunction()}>
                                    Delete
                                </LemonButton>
                            </>
                        }
                    />
                    <LemonDivider vertical />
                </>
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
                {templateId ? 'Create' : willReEnableOnSave ? 'Save & re-enable' : 'Save'}
            </LemonButton>
        </>
    )

    if (showPaygate) {
        return <PayGateMini feature={AvailableFeature.DATA_PIPELINES} />
    }

    return (
        <div className="space-y-3">
            <BindLogic logic={hogFunctionConfigurationLogic} props={logicProps}>
                <PageHeader
                    buttons={
                        <>
                            {headerButtons}
                            {saveButtons}
                        </>
                    }
                />

                <LemonBanner type="info">
                    Hog Functions are in <b>alpha</b> and are the next generation of our data pipeline destinations. You
                    can use pre-existing templates or modify the source Hog code to create your own custom functions.
                </LemonBanner>

                <Form
                    logic={hogFunctionConfigurationLogic}
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

                                    <div className="flex flex-col py-1 flex-1 justify-start">
                                        <span className="font-semibold">{configuration.name}</span>
                                    </div>

                                    <HogFunctionStatusIndicator />

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
                                                        <b>{hogFunction.template.name}</b>. If the template is updated,
                                                        this function is not affected unless you choose to update it.
                                                    </p>

                                                    <div className="flex flex-1 gap-2 items-center border-t pt-2">
                                                        <div className="flex-1">
                                                            <LemonButton>Close</LemonButton>
                                                        </div>
                                                        <LemonButton onClick={() => resetToTemplate()}>
                                                            Reset to template
                                                        </LemonButton>

                                                        <LemonButton
                                                            type="secondary"
                                                            onClick={() => duplicateFromTemplate()}
                                                        >
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
                            <div className="border bg-bg-light rounded p-3 space-y-2">
                                <LemonLabel>Expected volume</LemonLabel>
                                {sparkline ? (
                                    <>
                                        {sparkline.count > EVENT_THRESHOLD_ALERT_LEVEL ? (
                                            <LemonBanner type="warning">
                                                <b>Warning:</b> This destionation would have triggered{' '}
                                                <strong>
                                                    {sparkline.count ?? 0} time{sparkline.count !== 1 ? 's' : ''}
                                                </strong>{' '}
                                                in the last 7 days. Consider the impact of this function on your
                                                infrastructure.
                                            </LemonBanner>
                                        ) : (
                                            <p>
                                                This destination would have triggered{' '}
                                                <strong>
                                                    {sparkline.count ?? 0} time{sparkline.count !== 1 ? 's' : ''}
                                                </strong>{' '}
                                                in the last 7 days.
                                            </p>
                                        )}
                                        <div className="relative">
                                            {sparklineLoading ? <Spinner className="absolute bottom-0 left-0" /> : null}
                                            <Sparkline
                                                type="bar"
                                                className="w-full"
                                                data={[{ name: 'Matching events', values: sparkline.data }]}
                                                labels={sparkline.labels}
                                            />
                                        </div>
                                    </>
                                ) : sparklineLoading ? (
                                    <div>
                                        <Spinner />
                                    </div>
                                ) : null}
                            </div>
                        </div>

                        <div className="flex-2 min-w-100 space-y-4">
                            <div className="border bg-bg-light rounded p-3 space-y-2">
                                <div className="space-y-2">
                                    <HogFunctionInputs />

                                    {showSource ? (
                                        <>
                                            <LemonButton
                                                icon={<IconPlus />}
                                                size="small"
                                                type="secondary"
                                                className="my-4"
                                                onClick={() => {
                                                    setConfigurationValue('inputs_schema', [
                                                        ...(configuration.inputs_schema ?? []),
                                                        {
                                                            type: 'string',
                                                            key: `input_${
                                                                (configuration.inputs_schema?.length ?? 0) + 1
                                                            }`,
                                                            label: '',
                                                            required: false,
                                                        },
                                                    ])
                                                }}
                                            >
                                                Add input variable
                                            </LemonButton>
                                            <LemonField name="hog">
                                                {({ value, onChange }) => (
                                                    <>
                                                        <div className="flex justify-between gap-2">
                                                            <LemonLabel>Function source code</LemonLabel>
                                                            <LemonButton
                                                                size="xsmall"
                                                                type="secondary"
                                                                onClick={() => setShowSource(false)}
                                                            >
                                                                Hide source code
                                                            </LemonButton>
                                                        </div>
                                                        <CodeEditorResizeable
                                                            language="hog"
                                                            value={value ?? ''}
                                                            onChange={(v) => onChange(v ?? '')}
                                                            globals={exampleInvocationGlobalsWithInputs}
                                                            options={{
                                                                minimap: {
                                                                    enabled: false,
                                                                },
                                                                wordWrap: 'on',
                                                                scrollBeyondLastLine: false,
                                                                automaticLayout: true,
                                                                fixedOverflowWidgets: true,
                                                                suggest: {
                                                                    showInlineDetails: true,
                                                                },
                                                                quickSuggestionsDelay: 300,
                                                            }}
                                                        />
                                                    </>
                                                )}
                                            </LemonField>
                                        </>
                                    ) : (
                                        <div className="flex justify-end mt-2">
                                            <LemonButton
                                                size="xsmall"
                                                type="secondary"
                                                onClick={() => setShowSource(true)}
                                                disabledReason={
                                                    !hasAddon
                                                        ? 'Editing the source code requires the Data Pipelines addon'
                                                        : undefined
                                                }
                                            >
                                                Show function source code
                                            </LemonButton>
                                        </div>
                                    )}
                                </div>
                            </div>

                            {id ? <HogFunctionTest id={id} /> : <HogFunctionTestPlaceholder />}
                            <div className="flex gap-2 justify-end">{saveButtons}</div>
                        </div>
                    </div>
                </Form>
            </BindLogic>
        </div>
    )
}
