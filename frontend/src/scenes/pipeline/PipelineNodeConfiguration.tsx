import { LemonButton, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { IconLock } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import React from 'react'
import { BatchExportsEditFields } from 'scenes/batch_exports/BatchExportEditForm'
import { BatchExportConfigurationForm } from 'scenes/batch_exports/batchExportEditLogic'
import { getConfigSchemaArray, isValidField } from 'scenes/pipeline/configUtils'
import { PluginField } from 'scenes/plugins/edit/PluginField'

import { pipelineNodeLogic } from './pipelineNodeLogic'
import { PipelineBackend, PipelineNode } from './types'

export function PipelineNodeConfiguration(): JSX.Element {
    const { node, savedConfiguration, configuration, isConfigurationSubmitting, isConfigurable } =
        useValues(pipelineNodeLogic)
    const { resetConfiguration, submitConfiguration } = useActions(pipelineNodeLogic)

    return (
        <div className="space-y-3">
            {!node ? (
                Array(2)
                    .fill(null)
                    .map((_, index) => (
                        <div key={index} className="space-y-2">
                            <LemonSkeleton className="h-4 w-48" />
                            <LemonSkeleton className="h-9" />
                        </div>
                    ))
            ) : isConfigurable ? (
                <>
                    <Form logic={pipelineNodeLogic} formKey="configuration" className="space-y-3">
                        {node.backend === 'plugin' ? (
                            <PluginConfigurationFields node={node} formValues={configuration} />
                        ) : (
                            <BatchExportConfigurationFields node={node} formValues={configuration} />
                        )}
                        <div className="flex gap-2">
                            <LemonButton
                                type="secondary"
                                htmlType="reset"
                                onClick={() => resetConfiguration(savedConfiguration || {})}
                                disabledReason={isConfigurationSubmitting ? 'Saving in progress…' : undefined}
                            >
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                onClick={submitConfiguration}
                                loading={isConfigurationSubmitting}
                            >
                                Save
                            </LemonButton>
                        </div>
                    </Form>
                </>
            ) : (
                <span>This {node.stage} isn't configurable.</span>
            )}
        </div>
    )
}

function PluginConfigurationFields({
    node,
}: {
    node: PipelineNode & { backend: PipelineBackend.Plugin }
    formValues: Record<string, any>
}): JSX.Element {
    const { hiddenFields, requiredFields } = useValues(pipelineNodeLogic)

    const configSchemaArray = getConfigSchemaArray(node.plugin.config_schema)
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
                                    placement="topLeft"
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
    formValues,
}: {
    node: PipelineNode & { backend: PipelineBackend.BatchExport }
    formValues: Record<string, any>
}): JSX.Element {
    return (
        <BatchExportsEditFields
            isNew={false /* TODO */}
            isPipeline
            batchExportConfigForm={formValues as BatchExportConfigurationForm}
        />
    )
}
