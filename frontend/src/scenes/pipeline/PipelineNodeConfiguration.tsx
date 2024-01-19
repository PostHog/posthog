import { LemonSkeleton, LemonWidget, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { IconLock } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import React, { useEffect, useState } from 'react'
import { BatchExportsEditForm } from 'scenes/batch_exports/BatchExportEditForm'
import {
    defaultConfigForPlugin,
    determineInvisibleFields,
    determineRequiredFields,
    getConfigSchemaArray,
    isValidField,
} from 'scenes/pipeline/configUtils'
import { PluginField } from 'scenes/plugins/edit/PluginField'

import { pipelineNodeLogic } from './pipelineNodeLogic'
import { PipelineBackend, PipelineNode } from './types'

export function PipelineNodeConfiguration(): JSX.Element {
    const { node } = useValues(pipelineNodeLogic)

    return (
        <LemonWidget title="Configuration">
            {!node ? (
                <div className="space-y-3 m-3">
                    {Array(2)
                        .fill(null)
                        .map((_, index) => (
                            <div key={index} className="space-y-2">
                                <LemonSkeleton className="h-4 w-48" />
                                <LemonSkeleton className="h-9" />
                            </div>
                        ))}
                </div>
            ) : node.backend === 'plugin' ? (
                <PluginAppConfiguration node={node} />
            ) : (
                <BatchExportAppConfiguration node={node} />
            )}
        </LemonWidget>
    )
}

function PluginAppConfiguration({ node }: { node: PipelineNode & { backend: PipelineBackend.Plugin } }): JSX.Element {
    const { configuration } = useValues(pipelineNodeLogic)
    const { resetConfiguration, setConfigurationValues } = useActions(pipelineNodeLogic)

    const [invisibleFields, setInvisibleFields] = useState<string[]>([])
    const [requiredFields, setRequiredFields] = useState<string[]>([])

    const updateInvisibleAndRequiredFields = (): void => {
        setInvisibleFields(determineInvisibleFields((fieldName) => configuration[fieldName], node.plugin))
        setRequiredFields(determineRequiredFields((fieldName) => configuration[fieldName], node.plugin))
    }

    useEffect(() => {
        if (node) {
            setConfigurationValues({
                // Move this into pipelineNodeLogic
                ...(node.config || defaultConfigForPlugin(node.plugin)),
                __enabled: node.enabled,
            })
        } else {
            resetConfiguration()
        }
        updateInvisibleAndRequiredFields()
    }, [node])

    const configSchemaArray = getConfigSchemaArray(node.plugin.config_schema)

    if (configSchemaArray.length === 0) {
        return <p className="m-3 italic">This {node.stage} isn't configurable.</p>
    }

    const fields = configSchemaArray.map((fieldConfig, index) => (
        <React.Fragment key={fieldConfig.key || `__key__${index}`}>
            {fieldConfig.key &&
            fieldConfig.type &&
            isValidField(fieldConfig) &&
            !invisibleFields.includes(fieldConfig.key) ? (
                <Field
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
                    name={fieldConfig.key}
                    showOptional={!fieldConfig.required && !requiredFields.includes(fieldConfig.key)}
                >
                    <PluginField fieldConfig={fieldConfig} onChange={updateInvisibleAndRequiredFields} />
                </Field>
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

    return (
        <Form logic={pipelineNodeLogic} formKey="configuration" className="space-y-3 my-2 mx-3">
            {fields}
        </Form>
    )
}

function BatchExportAppConfiguration({
    node,
}: {
    node: PipelineNode & { backend: PipelineBackend.BatchExport }
}): JSX.Element {
    return (
        // TODO: Inline this, and remove Cancel/Save
        <div className="m-3">
            <BatchExportsEditForm id={node.id} />
        </div>
    )
}
