import { IconLock } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSwitch, LemonTextArea, SpinnerOverlay, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonSelectAction } from 'lib/components/ActionSelect'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
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
        actionMatchingEnabled,
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
                                    <IconLock />
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
        </>
    )

    return (
        <div className="space-y-3">
            <PageHeader buttons={buttons} />
            <Form
                logic={pipelinePluginConfigurationLogic}
                props={logicProps}
                formKey="configuration"
                className="space-y-3"
            >
                <div className="flex flex-wrap gap-4 items-start">
                    <div className="flex flex-col gap-4 flex-1 min-w-100">
                        <div className="border bg-bg-light rounded p-3 space-y-2">
                            <div className="flex flex-row gap-2 min-h-16 items-center">
                                <RenderApp plugin={plugin} imageSize="medium" />
                                <div className="flex flex-col py-1 flex-1">
                                    <div className="flex flex-row items-center font-semibold text-sm gap-1">
                                        {plugin.name}
                                    </div>
                                    {plugin.description ? (
                                        <div className="text-default text-xs text-text-secondary-3000 mt-1">
                                            <LemonMarkdown className="max-w-[30rem]" lowKeyHeadings>
                                                {plugin.description}
                                            </LemonMarkdown>
                                        </div>
                                    ) : null}
                                </div>

                                <LemonField name="enabled">
                                    {({ value, onChange }) => (
                                        <LemonSwitch
                                            label="Enabled"
                                            onChange={() => onChange(!value)}
                                            checked={value}
                                            disabled={loadingOrSubmitting}
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
                                <LemonInput type="text" disabled={loadingOrSubmitting} />
                            </LemonField>
                            <LemonField
                                name="description"
                                label="Description"
                                info="Add a description to share context with other team members"
                            >
                                <LemonTextArea disabled={loadingOrSubmitting} />
                            </LemonField>
                        </div>

                        {actionMatchingEnabled ? (
                            <div className="border bg-bg-light rounded p-3">
                                <LemonField
                                    name="match_action"
                                    label="Filter events by action"
                                    info="Create or select an action to filter events by. Only events that match this action will be processed."
                                >
                                    <LemonSelectAction allowClear disabled={loading} />
                                </LemonField>
                            </div>
                        ) : null}
                    </div>

                    <div className="border bg-bg-light rounded p-3 flex-2 min-w-100 space-y-2">
                        <>
                            {fields.length ? (
                                fields
                            ) : (
                                <span className="italic text-muted-alt">
                                    This app does not have specific configuration options
                                </span>
                            )}
                        </>
                    </div>
                </div>

                <div className="flex gap-2 justify-end">{buttons}</div>
            </Form>
        </div>
    )
}
