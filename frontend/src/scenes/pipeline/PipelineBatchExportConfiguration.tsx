import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { NotFound } from 'lib/components/NotFound'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { BatchExportGeneralEditFields, BatchExportsEditFields } from 'scenes/batch_exports/BatchExportEditForm'
import { BatchExportConfigurationForm } from 'scenes/batch_exports/batchExportEditLogic'

import { BATCH_EXPORT_SERVICE_NAMES, BatchExportService } from '~/types'

import { pipelineBatchExportConfigurationLogic } from './pipelineBatchExportConfigurationLogic'

export function PipelineBatchExportConfiguration({ service, id }: { service?: string; id?: string }): JSX.Element {
    if (service && !BATCH_EXPORT_SERVICE_NAMES.includes(service)) {
        return <NotFound object={`batch export service ${service}`} />
    }

    const logicProps = { service: (service as BatchExportService['type']) || null, id: id || null }
    const logic = pipelineBatchExportConfigurationLogic(logicProps)

    const { isNew, configuration, savedConfiguration, isConfigurationSubmitting, batchExportConfigLoading } =
        useValues(logic)
    const { resetConfiguration, submitConfiguration } = useActions(logic)

    if (batchExportConfigLoading) {
        return <Spinner />
    }

    return (
        <div className="space-y-3">
            <>
                <Form
                    logic={pipelineBatchExportConfigurationLogic}
                    props={logicProps}
                    formKey="configuration"
                    className="space-y-3"
                >
                    <LemonField
                        name="name"
                        label="Name"
                        info="Customising the name can be useful if multiple instances of the same type are used."
                    >
                        <LemonInput type="text" />
                    </LemonField>
                    <LemonField name="paused" info="Start in a paused state or continuously exporting from now">
                        {({ value, onChange }) => (
                            <LemonCheckbox label="Paused" onChange={() => onChange(!value)} checked={value} />
                        )}
                    </LemonField>
                    <BatchExportConfigurationFields
                        isNew={isNew}
                        formValues={configuration as BatchExportConfigurationForm}
                    />
                    <div className="flex gap-2">
                        <LemonButton
                            type="secondary"
                            htmlType="reset"
                            onClick={() => resetConfiguration(savedConfiguration || {})}
                            disabledReason={isConfigurationSubmitting ? 'Saving in progress…' : undefined}
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
                    </div>
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
