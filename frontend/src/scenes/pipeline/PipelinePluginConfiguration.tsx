import { IconLock } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonSwitch,
    LemonTag,
    LemonTextArea,
    SpinnerOverlay,
    Tooltip,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import React from 'react'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { getConfigSchemaArray, isValidField } from 'scenes/pipeline/configUtils'
import { PluginField } from 'scenes/plugins/edit/PluginField'

import { EntityTypes, PipelineStage } from '~/types'

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
        pluginFilteringEnabled,
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
                        <span className="flex flex-1 flex-row items-center">
                            <span className="flex-1">
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
                                {!requiredFields.includes(fieldConfig.key) ? (
                                    <span className="text-muted-alt"> (optional)</span>
                                ) : null}
                            </span>

                            {fieldConfig.templating && (
                                <Tooltip
                                    placement="bottom-start"
                                    title={
                                        <>
                                            This field supports templating. You can include properties from the event,
                                            person, related groups and more using curly brackets such as{' '}
                                            <code> {'{event.event}'} </code>
                                        </>
                                    }
                                >
                                    <LemonTag type="completion">Supports templating</LemonTag>
                                </Tooltip>
                            )}
                        </span>
                    }
                    help={fieldConfig.hint && <LemonMarkdown className="mt-0.5">{fieldConfig.hint}</LemonMarkdown>}
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

                        {pluginFilteringEnabled ? (
                            <div className="border bg-bg-light rounded p-3 space-y-2">
                                <LemonField name="filters" label="Filters by events and actions">
                                    {({ value, onChange }) => (
                                        <>
                                            <TestAccountFilterSwitch
                                                checked={value?.filter_test_accounts ?? false}
                                                onChange={(val) => onChange({ ...value, filter_test_accounts: val })}
                                                fullWidth
                                            />
                                            <ActionFilter
                                                bordered
                                                filters={value ?? {}}
                                                setFilters={(payload) => {
                                                    onChange({
                                                        ...payload,
                                                        filter_test_accounts: value?.filter_test_accounts,
                                                    })
                                                }}
                                                typeKey="plugin-filters"
                                                mathAvailability={MathAvailability.None}
                                                hideRename
                                                hideDuplicate
                                                showNestedArrow={false}
                                                actionsTaxonomicGroupTypes={[
                                                    TaxonomicFilterGroupType.Events,
                                                    TaxonomicFilterGroupType.Actions,
                                                ]}
                                                propertiesTaxonomicGroupTypes={[
                                                    TaxonomicFilterGroupType.EventProperties,
                                                    TaxonomicFilterGroupType.EventFeatureFlags,
                                                    TaxonomicFilterGroupType.Elements,
                                                    TaxonomicFilterGroupType.PersonProperties,
                                                ]}
                                                propertyFiltersPopover
                                                addFilterDefaultOptions={{
                                                    id: '$pageview',
                                                    name: '$pageview',
                                                    type: EntityTypes.EVENTS,
                                                }}
                                                buttonCopy="Add event filter"
                                            />
                                        </>
                                    )}
                                </LemonField>

                                <p className="italic text-muted-alt">
                                    This destination will be triggered if <b>any of</b> the above filters match.
                                </p>
                            </div>
                        ) : null}
                    </div>

                    <div className="flex-2 min-w-100 space-y-4">
                        <div className="border bg-bg-light rounded p-3  space-y-2">
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
                        <div className="flex gap-2 justify-end">{buttons}</div>
                    </div>
                </div>
            </Form>
        </div>
    )
}
