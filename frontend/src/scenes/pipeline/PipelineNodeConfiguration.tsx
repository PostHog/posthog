import { IconLock } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { NotFound } from 'lib/components/NotFound'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import React from 'react'
import { BatchExportsEditFields } from 'scenes/batch_exports/BatchExportEditForm'
import { BatchExportConfigurationForm } from 'scenes/batch_exports/batchExportEditLogic'
import { getConfigSchemaArray, isValidField } from 'scenes/pipeline/configUtils'
import { PluginField } from 'scenes/plugins/edit/PluginField'

import { AvailableFeature, PipelineStage, PluginType } from '~/types'

import { pipelineLogic } from './pipelineLogic'
import { pipelineNodeLogic } from './pipelineNodeLogic'

export function PipelineNodeConfiguration(): JSX.Element {
    const {
        stage,
        node,
        savedConfiguration,
        configuration,
        isConfigurationSubmitting,
        isConfigurable,
        newConfigurationPlugins,
        newConfigurationBatchExports,
        newConfigurationServiceOrPluginID,
        isNew,
        maybeNodePlugin,
    } = useValues(pipelineNodeLogic)
    const { resetConfiguration, submitConfiguration, setNewConfigurationServiceOrPluginID } =
        useActions(pipelineNodeLogic)
    const { canEnableNewDestinations } = useValues(pipelineLogic)

    let selector = <></>

    if (isNew) {
        if (!stage) {
            return <NotFound object="pipeline app stage" />
        }
        if (stage === PipelineStage.Destination && !canEnableNewDestinations) {
            return (
                <PayGateMini feature={AvailableFeature.DATA_PIPELINES}>
                    <></>
                </PayGateMini>
            )
        }
        const pluginsOptions = Object.values(newConfigurationPlugins).map((plugin) => ({
            value: plugin.id,
            label: plugin.name, // TODO: Ideally this would show RenderApp or MinimalAppView
        }))
        const batchExportsOptions = Object.entries(newConfigurationBatchExports).map(([key, name]) => ({
            value: key,
            label: name, // TODO: same render with a picture ?
        }))

        selector = (
            <LemonSelect
                value={newConfigurationServiceOrPluginID}
                onChange={(newValue) => {
                    setNewConfigurationServiceOrPluginID(newValue) // TODO: this should change the URL so we can link new specific plugin/batch export
                }}
                options={[...pluginsOptions, ...batchExportsOptions]}
            />
        )
    }

    return (
        <div className="space-y-3">
            {selector}
            {!node && !newConfigurationServiceOrPluginID ? (
                Array(2)
                    .fill(null)
                    .map((_, index) => (
                        <div key={index} className="space-y-2">
                            <LemonSkeleton className="h-4 w-48" />
                            <LemonSkeleton className="h-9" />
                        </div>
                    ))
            ) : (
                <>
                    <Form logic={pipelineNodeLogic} formKey="configuration" className="space-y-3">
                        <LemonField
                            name="name"
                            label="Name"
                            info="Customising the name can be useful if multiple instances of the same type are used."
                        >
                            <LemonInput type="text" />
                        </LemonField>
                        <LemonField
                            name="description"
                            label="Description"
                            info="Add a description to share context with other team members"
                        >
                            <LemonInput type="text" />
                        </LemonField>
                        {!isConfigurable ? (
                            <span>This {stage} isn't configurable.</span>
                        ) : maybeNodePlugin ? (
                            <PluginConfigurationFields plugin={maybeNodePlugin} formValues={configuration} />
                        ) : (
                            <BatchExportConfigurationFields isNew={isNew} formValues={configuration} />
                        )}
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
            )}
        </div>
    )
}

function PluginConfigurationFields({ plugin }: { plugin: PluginType; formValues: Record<string, any> }): JSX.Element {
    const { hiddenFields, requiredFields } = useValues(pipelineNodeLogic)

    const configSchemaArray = getConfigSchemaArray(plugin.config_schema)
    const fields = configSchemaArray.map((fieldConfig, index) => (
        <React.Fragment key={fieldConfig.key || `__key__${index}`}>
            {fieldConfig.key &&
            fieldConfig.type &&
            isValidField(fieldConfig) &&
            !hiddenFields.includes(fieldConfig.key) ? (
                <LemonField
                    name={fieldConfig.key}
                    label={
                        <>
                            {fieldConfig.secret && (
                                <Tooltip
                                    placement="top-start"
                                    title="This field is write-only. Its value won't be visible after saving."
                                >
                                    <IconLock className="ml-1.5" />
                                </Tooltip>
                            )}
                            {fieldConfig.markdown && <LemonMarkdown>{fieldConfig.markdown}</LemonMarkdown>}
                            {fieldConfig.name || fieldConfig.key}
                        </>
                    }
                    help={fieldConfig.hint && <LemonMarkdown className="mt-0.5">{fieldConfig.hint}</LemonMarkdown>}
                    showOptional={!requiredFields.includes(fieldConfig.key)}
                >
                    <PluginField fieldConfig={fieldConfig} />
                </LemonField>
            ) : (
                <>
                    {fieldConfig.type ? (
                        <p className="text-danger">
                            Invalid config field <i>{fieldConfig.name || fieldConfig.key}</i>.
                        </p>
                    ) : null}
                </>
            )}
        </React.Fragment>
    ))

    return <>{fields}</>
}

function BatchExportConfigurationFields({
    isNew,
    formValues,
}: {
    isNew: boolean
    formValues: Record<string, any>
}): JSX.Element {
    return (
        <BatchExportsEditFields
            isNew={isNew}
            isPipeline
            batchExportConfigForm={formValues as BatchExportConfigurationForm}
        />
    )
}
