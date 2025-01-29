import { IconPlus } from '@posthog/icons'
import { LemonSelect, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { EventSelect } from 'lib/components/EventSelect/EventSelect'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DatabaseTable } from 'scenes/data-management/database/DatabaseTable'

import { NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, BATCH_EXPORT_SERVICE_NAMES, BatchExportService } from '~/types'

import { BatchExportGeneralEditFields, BatchExportsEditFields } from './batch-exports/BatchExportEditForm'
import { BatchExportConfigurationForm } from './batch-exports/types'
import { humanizeBatchExportName } from './batch-exports/utils'
import { getDefaultConfiguration, pipelineBatchExportConfigurationLogic } from './pipelineBatchExportConfigurationLogic'
import { RenderBatchExportIcon } from './utils'

export function PipelineBatchExportConfiguration({ service, id }: { service?: string; id?: string }): JSX.Element {
    const logicProps = { service: (service as BatchExportService['type']) || null, id: id || null }
    const logic = pipelineBatchExportConfigurationLogic(logicProps)

    const {
        isNew,
        configuration,
        tables,
        savedConfiguration,
        isConfigurationSubmitting,
        batchExportConfigLoading,
        configurationChanged,
        batchExportConfig,
        selectedModel,
    } = useValues(logic)
    const { resetConfiguration, submitConfiguration, setSelectedModel, setConfigurationValue } = useActions(logic)
    const { featureFlags } = useValues(featureFlagLogic)
    const highFrequencyBatchExports = featureFlags[FEATURE_FLAGS.HIGH_FREQUENCY_BATCH_EXPORTS]

    if (service && !BATCH_EXPORT_SERVICE_NAMES.includes(service as any)) {
        return <NotFound object={`batch export service ${service}`} />
    }

    if (!batchExportConfig && batchExportConfigLoading) {
        return <SpinnerOverlay />
    }

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
        <div className="space-y-3">
            <>
                <PageHeader buttons={buttons} />
                <Form
                    logic={pipelineBatchExportConfigurationLogic}
                    props={logicProps}
                    formKey="configuration"
                    className="space-y-3"
                >
                    <div className="flex items-start gap-4 flex-wrap">
                        <div className="flex flex-col flex-1 min-w-100 space-y-3">
                            <div className="border bg-bg-light p-3 rounded space-y-2">
                                <div className="flex flex-row gap-2 min-h-16 items-center">
                                    {configuration.destination ? (
                                        <>
                                            <RenderBatchExportIcon size="medium" type={configuration.destination} />
                                            <div className="flex-1 font-semibold text-sm">
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
                            <div className="border bg-bg-light p-3 rounded space-y-2">
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
                                            }))}
                                            value={selectedModel}
                                            onSelect={(newValue) => {
                                                setSelectedModel(newValue)
                                            }}
                                            fullWidth={true}
                                        />
                                    </LemonField>
                                </div>
                                <div className="flex gap-2 min-h-16">
                                    <DatabaseTable
                                        table={selectedModel ? selectedModel : 'events'}
                                        tables={tables}
                                        inEditSchemaMode={false}
                                    />
                                </div>
                                {selectedModel === 'events' ? (
                                    <>
                                        <div className="flex flex-col gap-2 min-h-16">
                                            <div className="flex justify-between w-full gap-2">
                                                <LemonLabel>Include events</LemonLabel>
                                            </div>
                                            <p className="mb-0 text-xs text-muted-alt">
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
                                            <div className="flex justify-between w-full gap-2">
                                                <LemonLabel>Exclude events</LemonLabel>
                                            </div>
                                            <p className="mb-0 text-xs text-muted-alt">
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

                        <div className="flex-2 gap-4 space-y-4 min-w-100">
                            <div className="border bg-bg-light p-3 rounded">
                                <BatchExportConfigurationFields
                                    isNew={isNew}
                                    formValues={configuration as BatchExportConfigurationForm}
                                />
                            </div>
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
