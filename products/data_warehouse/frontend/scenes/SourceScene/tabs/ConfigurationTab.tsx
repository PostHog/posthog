import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect, useState } from 'react'

import { LemonButton, LemonDivider, LemonInputSelect, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { SourceFormComponent } from 'products/data_warehouse/frontend/shared/components/forms/SourceForm'

import { availableSourcesLogic } from '../../NewSourceScene/availableSourcesLogic'
import { buildKeaFormDefaultFromSourceDetails } from '../../NewSourceScene/sourceWizardLogic'
import { CDCSection } from './CDCSection'
import { sourceSettingsLogic } from './sourceSettingsLogic'

interface ConfigurationTabProps {
    id: string
}

export const ConfigurationTab = ({ id }: ConfigurationTabProps): JSX.Element => {
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesLogic)

    if (availableSourcesLoading) {
        return <LemonSkeleton />
    }

    return (
        <BindLogic logic={sourceSettingsLogic} props={{ id, availableSources }}>
            <UpdateSourceConnectionFormContainer />
        </BindLogic>
    )
}

function UpdateSourceConnectionFormContainer(): JSX.Element {
    const { sourceFieldConfig, source, sourceConfig, sourceConfigLoading } = useValues(sourceSettingsLogic)
    const { setSourceConfigValue } = useActions(sourceSettingsLogic)

    const [jobInputs, setJobInputs] = useState<Record<string, any>>({})

    useEffect(() => {
        if (!source || !sourceFieldConfig) {
            return
        }

        setSourceConfigValue(['access_method'], source.access_method ?? 'warehouse')
        setSourceConfigValue(['direct_query_enabled'], source.direct_query_enabled ?? false)
        setSourceConfigValue(['prefix'], source.prefix ?? '')
        setSourceConfigValue(['description'], source.description ?? '')
        setSourceConfigValue(['auto_sync_new_schemas'], source.auto_sync_new_schemas ?? false)
        setSourceConfigValue(['auto_sync_schema_patterns'], source.auto_sync_schema_patterns ?? [])
        setJobInputs({
            ...buildKeaFormDefaultFromSourceDetails({ [source.source_type]: sourceFieldConfig })['payload'],
            ...source.job_inputs,
        })
        // `source` is updating via a poll, and so we dont't want this updating when the object reference updates but not the actual data
        // It's also the reason why it can't live in the kea logic - the selector will update on object reference changes
    }, [
        source?.access_method,
        source?.direct_query_enabled,
        source?.prefix,
        source?.description,
        source?.auto_sync_new_schemas,
        setSourceConfigValue,
        // oxlint-disable-next-line exhaustive-deps
        JSON.stringify(source?.auto_sync_schema_patterns ?? []),
        // oxlint-disable-next-line exhaustive-deps
        JSON.stringify(source?.job_inputs ?? {}),
        // oxlint-disable-next-line exhaustive-deps
        JSON.stringify(sourceFieldConfig),
    ])

    if (!sourceFieldConfig || !source) {
        return <LemonSkeleton />
    }

    return (
        <>
            <span className="block mb-2">Overwrite your existing configuration here</span>
            <Form logic={sourceSettingsLogic} formKey="sourceConfig" enableFormOnSubmit>
                <SourceFormComponent
                    showPrefix={false}
                    showDescription={true}
                    showDirectQueryToggle
                    directQueryEditorUrl={
                        source.direct_query_enabled ? urls.sqlEditor({ connectionId: source.id }) : undefined
                    }
                    sourceConfig={sourceFieldConfig}
                    jobInputs={jobInputs}
                    initialAccessMethod={source.access_method ?? 'warehouse'}
                    setSourceConfigValue={setSourceConfigValue}
                />
                {source.access_method !== 'direct' && (
                    <>
                        <LemonDivider className="my-4" />
                        <div className="flex flex-col gap-2">
                            <LemonField
                                name="auto_sync_new_schemas"
                                help="New tables found on this source will start syncing automatically, using recommended sync settings."
                            >
                                {({ value, onChange }) => (
                                    <LemonSwitch
                                        bordered
                                        checked={value ?? false}
                                        onChange={onChange}
                                        label="Automatically sync new tables"
                                        data-attr="source-auto-sync-new-schemas"
                                    />
                                )}
                            </LemonField>
                            {sourceConfig?.auto_sync_new_schemas ? (
                                <LemonField
                                    name="auto_sync_schema_patterns"
                                    label="Only auto-sync tables matching"
                                    help="Use * and ? as wildcards, e.g. raw_*. Leave empty to auto-sync all new tables."
                                >
                                    {({ value, onChange }) => (
                                        <LemonInputSelect
                                            mode="multiple"
                                            allowCustomValues
                                            disableFiltering
                                            value={value ?? []}
                                            onChange={onChange}
                                            placeholder="raw_*"
                                            data-attr="source-auto-sync-schema-patterns"
                                        />
                                    )}
                                </LemonField>
                            ) : null}
                        </div>
                    </>
                )}
                <div className="my-4 flex flex-row justify-end gap-2">
                    <AccessControlAction
                        resourceType={AccessControlResourceType.ExternalDataSource}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={source.user_access_level}
                    >
                        <LemonButton
                            loading={sourceConfigLoading}
                            type="primary"
                            center
                            htmlType="submit"
                            data-attr="source-update"
                        >
                            Save
                        </LemonButton>
                    </AccessControlAction>
                </div>
            </Form>
            <CDCSection source={source} />
        </>
    )
}
