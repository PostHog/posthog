import { LemonSelect, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { useState } from 'react'
import { BatchExportGeneralEditFields, BatchExportsEditFields } from 'scenes/batch_exports/BatchExportEditForm'
import { BatchExportConfigurationForm } from 'scenes/batch_exports/batchExportEditLogic'
import { DatabaseTable } from 'scenes/data-management/database/DatabaseTable'

import { HogQLQueryEditor } from '~/queries/nodes/HogQLQuery/HogQLQueryEditor'
import { HogQLQuery, NodeKind } from '~/queries/schema'
import { BATCH_EXPORT_SERVICE_NAMES, BatchExportService } from '~/types'

import { pipelineBatchExportConfigurationLogic } from './pipelineBatchExportConfigurationLogic'
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
        isEditingModel,
        batchExportConfigLoading,
        configurationChanged,
        batchExportConfig,
        selectedModel,
    } = useValues(logic)
    const { resetConfiguration, submitConfiguration, setSelectedModel, setIsEditingModel, createOrUpdateCustomModel } =
        useActions(logic)

    const [localQuery, setLocalQuery] = useState<HogQLQuery>()
    const [queryChanged, setQueryChanged] = useState<boolean>(false)

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
                    <div className="flex items-start gap-2 flex-wrap">
                        <div className="border bg-bg-light p-3 rounded space-y-2 flex-1 min-w-100">
                            <div className="flex flex-row gap-2 min-h-16 items-center">
                                {configuration.destination ? (
                                    <>
                                        <RenderBatchExportIcon size="medium" type={configuration.destination} />
                                        <div className="flex-1 font-semibold text-sm">{configuration.destination}</div>
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

                            <LemonField
                                name="model"
                                label="Model"
                                info="A model defines the data that will be exported."
                            >
                                <LemonSelect
                                    options={tables.map((table) => ({ value: table.name, label: table.id }))}
                                    value={selectedModel?.name}
                                    onSelect={(newValue) => {
                                        const found = tables.find((table) => table.name == newValue)
                                        if (found) {
                                            setSelectedModel(found)
                                        }
                                    }}
                                />
                            </LemonField>

                            {!isEditingModel && (
                                <>
                                    <DatabaseTable
                                        table={selectedModel ? selectedModel.name : 'events'}
                                        tables={tables}
                                        inEditSchemaMode={false}
                                    />

                                    <LemonButton type="primary" onClick={() => setIsEditingModel(true)}>
                                        Edit
                                    </LemonButton>
                                </>
                            )}

                            {isEditingModel && selectedModel && (
                                <div className="mt-2">
                                    <span className="card-secondary">Update Model</span>
                                    <HogQLQueryEditor
                                        query={selectedModel.query}
                                        onChange={(queryInput) => {
                                            if (queryInput) {
                                                setLocalQuery({
                                                    kind: NodeKind.HogQLQuery,
                                                    query: queryInput,
                                                })

                                                if (queryInput !== selectedModel.query.query) {
                                                    setQueryChanged(true)
                                                }
                                            }
                                        }}
                                        editorFooter={(hasErrors, error, isValidView) => (
                                            <div className="flex flex-row gap-2 justify-between">
                                                <LemonButton
                                                    className="ml-2"
                                                    onClick={() => {
                                                        if (localQuery) {
                                                            createOrUpdateCustomModel(selectedModel, localQuery)
                                                            setIsEditingModel(false)
                                                        }
                                                    }}
                                                    type="primary"
                                                    center
                                                    disabledReason={
                                                        hasErrors
                                                            ? error ?? 'Query has errors'
                                                            : !isValidView
                                                            ? 'All fields must have an alias'
                                                            : !queryChanged
                                                            ? 'No changes to save'
                                                            : ''
                                                    }
                                                    data-attr="hogql-query-editor-save-as-view"
                                                >
                                                    Save
                                                </LemonButton>
                                                <LemonButton type="secondary" onClick={() => setIsEditingModel(false)}>
                                                    Cancel
                                                </LemonButton>
                                            </div>
                                        )}
                                    />
                                </div>
                            )}
                        </div>
                        <div className="border bg-bg-light p-3 rounded flex-2 min-w-100">
                            <BatchExportConfigurationFields
                                isNew={isNew}
                                formValues={configuration as BatchExportConfigurationForm}
                            />
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
