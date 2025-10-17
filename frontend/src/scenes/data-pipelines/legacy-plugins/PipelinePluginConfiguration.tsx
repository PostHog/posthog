import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import React, { useState } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'

import { IconLock, IconPencil } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonFileInput,
    LemonInput,
    LemonSelect,
    LemonSwitch,
    LemonTextArea,
    SpinnerOverlay,
    Tooltip,
} from '@posthog/lemon-ui'
import { PluginConfigSchema } from '@posthog/plugin-scaffold/src/types'

import { NotFound } from 'lib/components/NotFound'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { CodeEditor } from 'lib/monaco/CodeEditor'
import {
    SECRET_FIELD_VALUE,
    getConfigSchemaArray,
    isValidField,
} from 'scenes/data-pipelines/legacy-plugins/configUtils'

import { pipelinePluginConfigurationLogic } from './pipelinePluginConfigurationLogic'
import { RenderApp } from './utils'

export function PipelinePluginConfiguration({
    pluginId,
    pluginConfigId,
}: {
    pluginId?: number
    pluginConfigId?: number
}): JSX.Element {
    const logicProps = { pluginId: pluginId || null, pluginConfigId: pluginConfigId || null }
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
    const { submitConfiguration, resetConfiguration, migrateToHogFunction } = useActions(logic)

    if (loading && !plugin) {
        return <SpinnerOverlay />
    }

    if (!plugin) {
        return <NotFound object="plugin" />
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
        <div className="deprecated-space-y-3">
            <div className="flex justify-end w-full">
                <div className="shrink-0">{buttons}</div>
            </div>

            {plugin?.hog_function_migration_available && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Upgrade to new version',
                        onClick: () =>
                            LemonDialog.open({
                                title: 'Upgrade destination',
                                width: '30rem',
                                description:
                                    'This will create a new Destination in the upgraded system. The old destination will be disabled and can later be deleted. In addition there may be slight differences in the configuration options that you can choose to modify.',
                                secondaryButton: {
                                    type: 'secondary',
                                    children: 'Cancel',
                                },
                                primaryButton: {
                                    type: 'primary',
                                    onClick: () => migrateToHogFunction(),
                                    children: 'Upgrade',
                                },
                            }),
                        disabled: loading,
                    }}
                >
                    <b>New version available!</b> This destination is part of our legacy system. Click to upgrade.
                </LemonBanner>
            )}

            <Form
                logic={pipelinePluginConfigurationLogic}
                props={logicProps}
                formKey="configuration"
                className="deprecated-space-y-3"
            >
                <div className="flex flex-wrap gap-4 items-start">
                    <div className="flex flex-col flex-1 gap-4 min-w-100">
                        <div className="p-3 rounded border bg-surface-primary deprecated-space-y-2">
                            <div className="flex flex-row gap-2 items-center min-h-16">
                                <RenderApp plugin={plugin} imageSize="medium" />
                                <div className="flex flex-col flex-1 py-1">
                                    <div className="flex flex-row gap-1 items-center text-sm font-semibold">
                                        {plugin.name}
                                    </div>
                                    {plugin.description ? (
                                        <div className="mt-1 text-xs text-tertiary">
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
                        </div>{' '}
                    </div>

                    <div className="flex-2 min-w-100 deprecated-space-y-4">
                        <div className="p-3 rounded border bg-surface-primary deprecated-space-y-2">
                            <>
                                {fields.length ? (
                                    fields
                                ) : (
                                    <span className="italic text-secondary">
                                        This app does not have specific configuration options
                                    </span>
                                )}
                            </>
                        </div>
                        <div className="flex gap-2 justify-end">{buttons}</div>
                    </div>
                </div>
            </Form>
        </div>
    )
}

function PluginField({
    value,
    onChange,
    fieldConfig,
    disabled,
}: {
    value?: any
    onChange?: (value: any) => void
    fieldConfig: PluginConfigSchema
    disabled?: boolean
}): JSX.Element {
    const [editingSecret, setEditingSecret] = useState(false)
    if (
        fieldConfig.secret &&
        !editingSecret &&
        value &&
        (value === SECRET_FIELD_VALUE || value.name === SECRET_FIELD_VALUE)
    ) {
        return (
            <LemonButton
                type="secondary"
                icon={<IconPencil />}
                onClick={() => {
                    onChange?.(fieldConfig.default || '')
                    setEditingSecret(true)
                }}
                disabled={disabled}
            >
                Reset secret {fieldConfig.type === 'attachment' ? 'attachment' : 'field'}
            </LemonButton>
        )
    }

    return fieldConfig.type === 'attachment' ? (
        <>
            {value?.name ? <span>Selected file: {value.name}</span> : null}
            <LemonFileInput
                accept="*"
                multiple={false}
                onChange={(files) => onChange?.(files[0])}
                value={value?.size ? [value] : []}
                showUploadedFiles={false}
            />
        </>
    ) : fieldConfig.type === 'string' ? (
        <LemonInput
            value={value}
            onChange={onChange}
            autoFocus={editingSecret}
            className="ph-no-capture"
            disabled={disabled}
        />
    ) : fieldConfig.type === 'json' ? (
        <JsonConfigField value={value} onChange={onChange} autoFocus={editingSecret} className="ph-no-capture" />
    ) : fieldConfig.type === 'choice' ? (
        <LemonSelect
            fullWidth
            value={value}
            className="ph-no-capture"
            onChange={onChange}
            options={fieldConfig.choices.map((choice) => {
                return { label: choice, value: choice }
            })}
            disabled={disabled}
        />
    ) : (
        <strong className="text-danger">
            Unknown field type "<code>{fieldConfig.type}</code>".
            <br />
            You may need to upgrade PostHog!
        </strong>
    )
}

function JsonConfigField(props: {
    onChange?: (value: any) => void
    className: string
    autoFocus: boolean
    value: any
}): JSX.Element {
    return (
        <AutoSizer disableWidth className="min-h-60">
            {({ height }) => (
                <CodeEditor
                    className="border"
                    language="json"
                    value={props.value}
                    onChange={(v) => props.onChange?.(v ?? '')}
                    height={height}
                    options={{
                        minimap: {
                            enabled: false,
                        },
                    }}
                />
            )}
        </AutoSizer>
    )
}
