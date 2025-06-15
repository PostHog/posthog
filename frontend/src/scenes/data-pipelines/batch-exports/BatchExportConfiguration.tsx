import { IconCheckCircle, IconPlus, IconX } from '@posthog/icons'
import { LemonSelect, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { EventSelect } from 'lib/components/EventSelect/EventSelect'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { Spinner, SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DatabaseTable } from 'scenes/data-management/database/DatabaseTable'

import { NodeKind } from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    BATCH_EXPORT_SERVICE_NAMES,
    BatchExportConfigurationTest,
    BatchExportConfigurationTestStep,
    BatchExportService,
} from '~/types'

import { batchExportConfigurationLogic, getDefaultConfiguration } from './batchExportConfigurationLogic'
import { BatchExportGeneralEditFields, BatchExportsEditFields } from './BatchExportEditForm'
import { RenderBatchExportIcon } from './BatchExportIcon'
import { BatchExportConfigurationForm } from './types'
import { humanizeBatchExportName, normalizeBatchExportService } from './utils'

export function BatchExportConfiguration({ service, id }: { service?: string; id?: string }): JSX.Element {
    service = normalizeBatchExportService(service ?? '')
    const logicProps = { service: (service as BatchExportService['type']) || null, id: id || null }
    const logic = batchExportConfigurationLogic(logicProps)

    const {
        isNew,
        batchExportConfigTest,
        batchExportConfigTestLoading,
        configuration,
        tables,
        savedConfiguration,
        isConfigurationSubmitting,
        batchExportConfigLoading,
        configurationChanged,
        batchExportConfig,
        selectedModel,
        runningStep,
    } = useValues(logic)
    const {
        resetConfiguration,
        submitConfiguration,
        setSelectedModel,
        setConfigurationValue,
        runBatchExportConfigTestStep,
    } = useActions(logic)
    const { featureFlags } = useValues(featureFlagLogic)
    const highFrequencyBatchExports = featureFlags[FEATURE_FLAGS.HIGH_FREQUENCY_BATCH_EXPORTS]
    const sessionsBatchExports = featureFlags[FEATURE_FLAGS.SESSIONS_BATCH_EXPORTS]

    if (service && !BATCH_EXPORT_SERVICE_NAMES.includes(service as BatchExportService['type'])) {
        return <NotFound object={`batch export service ${service}`} />
    }

    if (!batchExportConfig && batchExportConfigLoading) {
        return <SpinnerOverlay />
    }

    if (!batchExportConfigTest && batchExportConfigTestLoading) {
        return <SpinnerOverlay />
    }

    const requiredFields = ['interval']
    const requiredFieldsMissing = requiredFields.filter((field) => !configuration[field])

    const buttons = (
        <>
            <LemonButton
                type="secondary"
                htmlType="reset"
                onClick={() =>
                    isNew && service
                        ? resetConfiguration(getDefaultConfiguration(service))
                        : resetConfiguration(savedConfiguration)
                }
                disabledReason={
                    !configurationChanged ? 'No changes' : isConfigurationSubmitting ? 'Saving in progress…' : undefined
                }
            >
                {isNew ? 'Reset' : 'Cancel'}
            </LemonButton>
            <LemonButton
                type="primary"
                htmlType="submit"
                onClick={submitConfiguration}
                loading={isConfigurationSubmitting}
                disabledReason={
                    !configurationChanged
                        ? 'No changes to save'
                        : isConfigurationSubmitting
                        ? 'Saving in progress…'
                        : undefined
                }
            >
                {isNew ? 'Create' : 'Save'}
            </LemonButton>
        </>
    )

    return (
        <div className="deprecated-space-y-3">
            <>
                <PageHeader buttons={buttons} />
                <Form
                    logic={batchExportConfigurationLogic}
                    props={logicProps}
                    formKey="configuration"
                    className="deprecated-space-y-3"
                >
                    <div className="flex flex-wrap gap-4 items-start">
                        <div className="flex flex-col flex-1 min-w-100 deprecated-space-y-3">
                            <div className="p-3 rounded border bg-surface-primary deprecated-space-y-2">
                                <div className="flex flex-row gap-2 items-center min-h-16">
                                    {configuration.destination ? (
                                        <>
                                            <RenderBatchExportIcon size="medium" type={configuration.destination} />
                                            <div className="flex-1 text-sm font-semibold">
                                                {humanizeBatchExportName(configuration.destination)}
                                            </div>
                                        </>
                                    ) : (
                                        <div className="flex-1" />
                                    )}

                                    <LemonField
                                        name="paused"
                                        info="Start in a paused state or continuously exporting from now"
                                    >
                                        {({ value, onChange }) => (
                                            <LemonSwitch
                                                label="Enabled"
                                                onChange={() => onChange(!value)}
                                                checked={!value}
                                                bordered
                                            />
                                        )}
                                    </LemonField>
                                </div>

                                <LemonField
                                    name="name"
                                    label="Name"
                                    info="Customizing the name can be useful if multiple instances of the same type are used."
                                >
                                    <LemonInput type="text" />
                                </LemonField>

                                <div className="flex gap-2 min-h-16">
                                    <LemonField
                                        name="interval"
                                        label="Interval"
                                        className="flex-1"
                                        info={
                                            <>
                                                Dictates the frequency of batch export runs. For example, if you select
                                                hourly, a new batch export run will start every hour.
                                            </>
                                        }
                                    >
                                        <LemonSelect
                                            options={[
                                                { value: 'hour', label: 'Hourly' },
                                                { value: 'day', label: 'Daily' },
                                                {
                                                    value: 'every 5 minutes',
                                                    label: 'Every 5 minutes',
                                                    hidden: !highFrequencyBatchExports,
                                                },
                                            ]}
                                        />
                                    </LemonField>
                                </div>
                            </div>
                            <div className="p-3 rounded border bg-surface-primary deprecated-space-y-2">
                                <div className="flex gap-2 min-h-16">
                                    <LemonField
                                        name="model"
                                        label="Model"
                                        info="A model defines the data that will be exported."
                                        className="flex flex-1"
                                    >
                                        <LemonSelect
                                            options={tables.map((table) => ({
                                                value: table.name,
                                                label: table.id,
                                                hidden: !sessionsBatchExports && table.name === 'sessions',
                                            }))}
                                            value={selectedModel}
                                            onSelect={(newValue) => {
                                                setSelectedModel(newValue)
                                            }}
                                            fullWidth={true}
                                        />
                                    </LemonField>
                                </div>

                                <div className="flex gap-2">
                                    <LemonCollapse
                                        className="flex flex-1"
                                        panels={[
                                            {
                                                key: 'schema',
                                                header: 'View model schema',
                                                content: (
                                                    <div className="flex-1">
                                                        <DatabaseTable
                                                            table={selectedModel ? selectedModel : 'events'}
                                                            tables={tables}
                                                            inEditSchemaMode={false}
                                                        />
                                                    </div>
                                                ),
                                            },
                                        ]}
                                    />
                                </div>
                                {selectedModel === 'events' ? (
                                    <>
                                        <div className="flex flex-col gap-2 min-h-16">
                                            <div className="flex gap-2 justify-between w-full">
                                                <LemonLabel>Include events</LemonLabel>
                                            </div>
                                            <p className="mb-0 text-xs text-secondary">
                                                If set, the batch export will <b>only</b> export events matching any of
                                                the below. If left unset, all events will be exported.
                                            </p>
                                            <EventSelect
                                                onChange={(includedEvents) => {
                                                    const filteredEvents = includedEvents.filter(
                                                        (event) => event != null
                                                    )
                                                    setConfigurationValue('include_events', filteredEvents)
                                                }}
                                                selectedEvents={
                                                    configuration.include_events ? configuration.include_events : []
                                                }
                                                addElement={
                                                    <LemonButton
                                                        size="small"
                                                        type="secondary"
                                                        icon={<IconPlus />}
                                                        sideIcon={null}
                                                    >
                                                        Include event
                                                    </LemonButton>
                                                }
                                            />
                                        </div>
                                        <div className="flex flex-col gap-2 min-h-16">
                                            <div className="flex gap-2 justify-between w-full">
                                                <LemonLabel>Exclude events</LemonLabel>
                                            </div>
                                            <p className="mb-0 text-xs text-secondary">
                                                If set, the batch export will <b>exclude</b> events matching any of the
                                                below. If left unset, no events will be excluded from the export.
                                            </p>
                                            <EventSelect
                                                onChange={(excludedEvents) => {
                                                    const filteredEvents = excludedEvents.filter(
                                                        (event) => event != null
                                                    )
                                                    setConfigurationValue('exclude_events', filteredEvents)
                                                }}
                                                selectedEvents={
                                                    configuration.exclude_events ? configuration.exclude_events : []
                                                }
                                                addElement={
                                                    <LemonButton
                                                        size="small"
                                                        type="secondary"
                                                        icon={<IconPlus />}
                                                        sideIcon={null}
                                                    >
                                                        Exclude event
                                                    </LemonButton>
                                                }
                                            />
                                        </div>
                                        <div className="flex gap-2 min-h-16">
                                            <LemonField name="filters" label="Filters" className="flex flex-1">
                                                <PropertyFilters
                                                    propertyFilters={
                                                        (configuration.filters
                                                            ? configuration.filters
                                                            : []) as AnyPropertyFilter[]
                                                    }
                                                    taxonomicGroupTypes={
                                                        selectedModel === 'events'
                                                            ? [TaxonomicFilterGroupType.EventProperties]
                                                            : [TaxonomicFilterGroupType.PersonProperties]
                                                    }
                                                    onChange={(filters: AnyPropertyFilter[]) => {
                                                        setConfigurationValue('filters', filters)
                                                    }}
                                                    pageKey={`BatchExportsPropertyFilters.${
                                                        batchExportConfig ? batchExportConfig.id : 'New'
                                                    }`}
                                                    metadataSource={{ kind: NodeKind.ActorsQuery }}
                                                />
                                            </LemonField>
                                        </div>
                                    </>
                                ) : null}
                            </div>
                        </div>

                        <div className="gap-4 flex-2 deprecated-space-y-4 min-w-100">
                            <div className="p-3 rounded border bg-surface-primary">
                                <BatchExportConfigurationFields
                                    isNew={isNew}
                                    formValues={configuration as BatchExportConfigurationForm}
                                />
                            </div>
                            {batchExportConfigTest && (
                                <div className="p-3 rounded border bg-surface-primary">
                                    <BatchExportConfigurationTests
                                        batchExportConfigTest={batchExportConfigTest}
                                        batchExportConfigTestLoading={batchExportConfigTestLoading}
                                        runningStep={runningStep}
                                        runBatchExportConfigTestStep={runBatchExportConfigTestStep}
                                        requiredFieldsMissing={requiredFieldsMissing}
                                    />
                                </div>
                            )}
                        </div>
                    </div>
                    <div className="flex gap-2 justify-end">{buttons}</div>
                </Form>
            </>
        </div>
    )
}

function BatchExportConfigurationFields({
    isNew,
    formValues,
}: {
    isNew: boolean
    formValues: BatchExportConfigurationForm
}): JSX.Element {
    return (
        <>
            <BatchExportGeneralEditFields isNew={isNew} isPipeline batchExportConfigForm={formValues} />
            <BatchExportsEditFields isNew={isNew} batchExportConfigForm={formValues} />
        </>
    )
}

export function BatchExportConfigurationTests({
    batchExportConfigTest,
    batchExportConfigTestLoading,
    runningStep,
    runBatchExportConfigTestStep,
    requiredFieldsMissing,
}: {
    batchExportConfigTest: BatchExportConfigurationTest
    batchExportConfigTestLoading: boolean
    runningStep: number | null
    runBatchExportConfigTestStep: (step: any) => void
    requiredFieldsMissing: string[]
}): JSX.Element | null {
    if (!batchExportConfigTest && batchExportConfigTestLoading) {
        return (
            <div className="flex justify-center items-center p-4">
                <Spinner />
            </div>
        )
    }

    if (!batchExportConfigTest || !batchExportConfigTest.steps) {
        return null
    }

    const renderStatusIcon = (step: BatchExportConfigurationTestStep, index: number): JSX.Element => {
        if (!step.result || runningStep === index) {
            return <Spinner />
        }

        return step.result.status === 'Passed' ? (
            <IconCheckCircle className="text-green-500 shrink-0" />
        ) : (
            <IconX className="text-red-500 shrink-0" />
        )
    }

    const header = (
        <div className="space-y-2">
            <h2 className="flex gap-2 items-center m-0 text-lg font-semibold">Test configuration</h2>
            <p className="text-xs text-secondary">
                Test the batch export's configuration to uncover errors before saving it
            </p>
        </div>
    )

    if (requiredFieldsMissing.length > 0) {
        return (
            <div className="space-y-4">
                {header}
                <LemonBanner type="info">
                    Please select a value for the following fields before testing the configuration:{' '}
                    {requiredFieldsMissing.join(', ')}
                </LemonBanner>
            </div>
        )
    }

    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center">
                {header}
                <LemonButton
                    onClick={() => runBatchExportConfigTestStep(0)}
                    disabledReason={runningStep !== null ? 'Test step is running' : null}
                    size="small"
                    type="primary"
                >
                    {runningStep ? 'Testing...' : 'Start test'}
                </LemonButton>
            </div>

            <div className="space-y-4">
                {batchExportConfigTest.steps.map((step, index) => {
                    // Only render if the step has a result or is currently running
                    if (!step.result && index !== runningStep) {
                        return null
                    }

                    return (
                        <div key={`${step.name}-${index}`}>
                            <div className="flex gap-2 items-start">
                                <div className="mt-1">{renderStatusIcon(step, index)}</div>
                                <div className="flex-1">
                                    <LemonLabel info={step.description} className="mb-2">
                                        {step.name}
                                    </LemonLabel>
                                    {step.result && (
                                        <div className="mt-2">
                                            <LemonBanner type={step.result.status === 'Passed' ? 'success' : 'error'}>
                                                {step.result.status === 'Passed' ? 'Success' : `${step.result.message}`}
                                            </LemonBanner>
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
