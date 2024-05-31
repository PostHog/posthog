import { LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { BatchExportGeneralEditFields, BatchExportsEditFields } from 'scenes/batch_exports/BatchExportEditForm'
import { BatchExportConfigurationForm } from 'scenes/batch_exports/batchExportEditLogic'

import { BATCH_EXPORT_SERVICE_NAMES, BatchExportService } from '~/types'

import { PipelineNodeFilters } from './components/PipelineNodeFilters'
import { pipelineBatchExportConfigurationLogic } from './pipelineBatchExportConfigurationLogic'
import { RenderBatchExportIcon } from './utils'

export function PipelineBatchExportConfiguration({ service, id }: { service?: string; id?: string }): JSX.Element {
    const logicProps = { service: (service as BatchExportService['type']) || null, id: id || null }
    const logic = pipelineBatchExportConfigurationLogic(logicProps)

    const {
        isNew,
        configuration,
        savedConfiguration,
        isConfigurationSubmitting,
        batchExportConfigLoading,
        configurationChanged,
        batchExportConfig,
        filteringEnabled,
    } = useValues(logic)
    const { resetConfiguration, submitConfiguration } = useActions(logic)

    if (service && !BATCH_EXPORT_SERVICE_NAMES.includes(service)) {
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
                onClick={() => resetConfiguration(savedConfiguration || {})}
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
                    <div className="flex flex-wrap gap-4 items-start">
                        <div className="flex flex-col gap-4 flex-1 min-w-100">
                            <div className="border bg-bg-light rounded p-3 space-y-2">
                                <div className="flex flex-row gap-2 min-h-16 items-center">
                                    {configuration.destination ? (
                                        <>
                                            <RenderBatchExportIcon size="medium" type={configuration.destination} />
                                            <div className="flex-1 font-semibold text-sm">
                                                {configuration.destination}
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

                            {filteringEnabled ? (
                                <PipelineNodeFilters
                                    description={
                                        <>
                                            The exported will to only include events that match any of the above
                                            filters.
                                        </>
                                    }
                                />
                            ) : null}
                        </div>
                        <div className="border bg-bg-light p-3 rounded flex-2 min-w-100">
                            <BatchExportGeneralEditFields
                                isNew={isNew}
                                isPipeline
                                batchExportConfigForm={configuration as BatchExportConfigurationForm}
                            />
                            <BatchExportsEditFields
                                isNew={isNew}
                                isPipeline
                                batchExportConfigForm={configuration as BatchExportConfigurationForm}
                            />
                        </div>
                    </div>
                    <div className="flex gap-2 justify-end">{buttons}</div>
                </Form>
            </>
        </div>
    )
}
