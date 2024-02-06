import { LemonSkeleton, LemonWidget, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { IconLock } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import React, { useEffect, useState } from 'react'
import {
    defaultConfigForPlugin,
    determineInvisibleFields,
    determineRequiredFields,
    getConfigSchemaArray,
    isValidField,
} from 'scenes/pipeline/configUtils'
import { PluginField } from 'scenes/plugins/edit/PluginField'

import { pipelineAppLogic } from './pipelineAppLogic'

export function PipelineAppConfiguration(): JSX.Element {
    const { appBackend } = useValues(pipelineAppLogic)

    if (appBackend === 'plugin') {
        return (
            <LemonWidget title="Configuration">
                <WebhookAppConfiguration />
            </LemonWidget>
        )
    }

    return <p>Unsupported app type</p>
}

function WebhookAppConfiguration(): JSX.Element {
    const { maybePlugin, maybePluginConfig, configuration, kind } = useValues(pipelineAppLogic)
    const { resetConfiguration, setConfigurationValues } = useActions(pipelineAppLogic)

    const [invisibleFields, setInvisibleFields] = useState<string[]>([])
    const [requiredFields, setRequiredFields] = useState<string[]>([])

    const updateInvisibleAndRequiredFields = (): void => {
        setInvisibleFields(
            maybePlugin ? determineInvisibleFields((fieldName) => configuration[fieldName], maybePlugin) : []
        )
        setRequiredFields(
            maybePlugin ? determineRequiredFields((fieldName) => configuration[fieldName], maybePlugin) : []
        )
    }

    useEffect(() => {
        if (maybePlugin && maybePluginConfig) {
            setConfigurationValues({
                ...(maybePluginConfig.config || defaultConfigForPlugin(maybePlugin)),
                __enabled: maybePluginConfig.enabled,
            })
        } else {
            resetConfiguration()
        }
        updateInvisibleAndRequiredFields()
    }, [maybePlugin?.id, maybePlugin?.config_schema])

    if (!maybePlugin) {
        // This will never show up when we realize that the plugin doesn't exist, since then the whole scene is NotFound
        return (
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
        )
    }

    const configSchemaArray = getConfigSchemaArray(maybePlugin.config_schema)

    if (configSchemaArray.length === 0) {
        return <p className="m-3 italic">This {kind} isn't configurable.</p>
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
        <Form logic={pipelineAppLogic} formKey="configuration" className="space-y-3 my-2 mx-3">
            {fields}
        </Form>
    )
}
