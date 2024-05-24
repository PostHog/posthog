import { IconLock } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonTextArea, SpinnerOverlay, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { NotFound } from 'lib/components/NotFound'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import React from 'react'
import { getConfigSchemaArray, isValidField } from 'scenes/pipeline/configUtils'
import { PluginField } from 'scenes/plugins/edit/PluginField'

import { PipelineStage } from '~/types'

import { pipelinePluginConfigurationLogic } from './pipelinePluginConfigurationLogic'
import { RenderApp } from './utils'

export function PipelinePluginConfiguration({
    stage,
    pluginId,
    pluginConfigId,
}: {
    stage: PipelineStage
    pluginId?: number
    pluginConfigId?: number
}): JSX.Element {
    const logicProps = { stage: stage, pluginId: pluginId || null, pluginConfigId: pluginConfigId || null }
    const logic = pipelinePluginConfigurationLogic(logicProps)

    const {
        plugin,
        isNew,
        isConfigurationSubmitting,
        savedConfiguration,
        hiddenFields,
        requiredFields,
        loading,
        configurationChanged,
    } = useValues(logic)
    const { submitConfiguration, resetConfiguration } = useActions(logic)

    if (!stage) {
        return <NotFound object="pipeline stage" />
    }

    if (loading && !plugin) {
        return <SpinnerOverlay />
    }

    if (!plugin) {
        return <NotFound object={`pipeline ${stage}`} />
    }

    const loadingOrSubmitting = loading || isConfigurationSubmitting

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
                    <PluginField fieldConfig={fieldConfig} disabled={loadingOrSubmitting} />
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

    return (
        <div className="space-y-3">
            <div className="flex flex-row gap-2">
                <RenderApp plugin={plugin} imageSize="medium" />
                <div className="flex flex-col py-1">
                    <div className="flex flex-row items-center font-semibold text-sm gap-1">{plugin.name}</div>
                    {plugin.description ? (
                        <div className="text-default text-xs text-text-secondary-3000 mt-1">
                            <LemonMarkdown className="max-w-[30rem]" lowKeyHeadings>
                                {plugin.description}
                            </LemonMarkdown>
                        </div>
                    ) : null}
                </div>
            </div>

            <Form
                logic={pipelinePluginConfigurationLogic}
                props={logicProps}
                formKey="configuration"
                className="space-y-3"
            >
                <LemonField
                    name="name"
                    label="Name"
                    info="Customising the name can be useful if multiple instances of the same type are used."
                >
                    <LemonInput type="text" disabled={loadingOrSubmitting} />
                </LemonField>
                <LemonField
                    name="description"
                    label="Description"
                    info="Add a description to share context with other team members"
                >
                    <LemonTextArea disabled={loadingOrSubmitting} />
                </LemonField>
                <LemonField name="enabled">
                    {({ value, onChange }) => (
                        <LemonCheckbox
                            label="Enabled"
                            onChange={() => onChange(!value)}
                            checked={value}
                            disabled={loadingOrSubmitting}
                        />
                    )}
                </LemonField>
                <>{fields}</>
                <div className="flex gap-2">
                    <LemonButton
                        type="secondary"
                        htmlType="reset"
                        onClick={() => resetConfiguration(savedConfiguration || {})}
                        disabledReason={
                            isConfigurationSubmitting
                                ? 'Saving in progress…'
                                : !configurationChanged
                                ? 'No changes'
                                : undefined
                        }
                    >
                        Clear changes
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
        </div>
    )
}
