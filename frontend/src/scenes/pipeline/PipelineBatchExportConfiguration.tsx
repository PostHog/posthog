import { LemonSelect, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DatabaseTable } from 'scenes/data-management/database/DatabaseTable'

import { BATCH_EXPORT_SERVICE_NAMES, BatchExportService } from '~/types'

import {
    BatchExportGeneralEditFields,
    BatchExportsEditFields,
    BatchExportsEditModel,
} from './batch-exports/BatchExportEditForm'
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
        showEditor,
        batchExportHogQLQueryLoading,
    } = useValues(logic)
    const { resetConfiguration, submitConfiguration, setSelectedModel, setShowEditor } = useActions(logic)
    const { featureFlags } = useValues(featureFlagLogic)
    const highFrequencyBatchExports = featureFlags[FEATURE_FLAGS.HIGH_FREQUENCY_BATCH_EXPORTS]

    if (service && !BATCH_EXPORT_SERVICE_NAMES.includes(service as any)) {
        return <NotFound object={`batch export service ${service}`} />
    }

    if ((!batchExportConfig && batchExportConfigLoading) || (!batchExportConfig?.hogql_query && batchExportHogQLQueryLoading)) {
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
        <div className="space-y-3 gap-4">
            <>
                <PageHeader buttons={buttons} />
                <Form
                    logic={pipelineBatchExportConfigurationLogic}
                    props={logicProps}
                    formKey="configuration"
                    className="space-y-3"
                >
                    <div className="flex items-start gap-4 flex-wrap">
                        <div className="flex-col flex min-w-100 space-y-3">
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
                                                label="Paused"
                                                onChange={() => onChange(!value)}
                                                checked={value}
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
                                    <LemonInput type="text" />
                                </LemonField>

                            </div>

                            <div className="border bg-bg-light p-3 rounded space-y-2">
                                <div className="flex flex-row gap-2 min-h-16 items-center">

                                    <LemonField
                                        name="interval"
                                        label="Interval"
                                        className="flex-1"
                                        info={
                                            <>
                                                Dictates the frequency of batch export runs. For example, if you select hourly, the batch export will run every hour.
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
                        </div>

                        <BatchExportConfigurationFields
                            isNew={isNew}
                            formValues={configuration as BatchExportConfigurationForm}
                            selectedModel={selectedModel}
                            setSelectedModel={setSelectedModel}
                            showEditor={showEditor}
                            setShowEditor={setShowEditor}
                            tables={tables}
                        />
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
    selectedModel,
    setSelectedModel,
    showEditor,
    setShowEditor,
    tables,
}: {
    isNew: boolean
    formValues: BatchExportConfigurationForm
}): JSX.Element {
    return (
        <>
            <div className="flex-2 gap-4 space-y-3">
            <div className="border bg-bg-light p-3 rounded flex-2 min-w-100">

            <BatchExportGeneralEditFields isNew={isNew} isPipeline batchExportConfigForm={formValues} />
                <BatchExportsEditFields isNew={isNew} batchExportConfigForm={formValues} />
            </div>

            <div className="border bg-bg-light p-3 rounded flex-2 min-w-100">

                <BatchExportsEditModel isNew={isNew} batchExportConfigForm={formValues} selectedModel={selectedModel} tables={tables} setSelectedModel={setSelectedModel} query={formValues.hogql_query} setQuery={(newQuery) => {formValues.hogql_query = newQuery}} showEditor={showEditor} setShowEditor={setShowEditor}/>
            </div>
            </div>
        </>
    )
}
