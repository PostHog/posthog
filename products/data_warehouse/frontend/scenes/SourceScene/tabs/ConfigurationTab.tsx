import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect, useRef, useState } from 'react'

import { LemonBanner, LemonButton, LemonDivider, LemonInputSelect, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'
import type { ExternalDataSource } from '~/types'

import { SourceFormComponent } from 'products/data_warehouse/frontend/shared/components/forms/SourceForm'

import { availableSourcesLogic } from '../../NewSourceScene/availableSourcesLogic'
import { buildKeaFormDefaultFromSourceDetails } from '../../NewSourceScene/sourceWizardLogic'
import { CDCSection } from './CDCSection'
import { sourceSettingsLogic } from './sourceSettingsLogic'

interface ConfigurationTabProps {
    id: string
}

const GOOGLE_CLOUD_CREDENTIAL_FIELD_ID = 'source-field-google_cloud_service_account_integration_id'

export function isGoogleServiceAccountAuthNotYetOnIntegrations(source: ExternalDataSource | null): boolean {
    // Only supports BigQuery for now
    if (!source || source.source_type !== 'BigQuery') {
        return false
    }

    const jobInputs = (source.job_inputs ?? {}) as Record<string, any>
    return !jobInputs.google_cloud_service_account_integration_id
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
    const { sourceFieldConfig, source, sourceConfig, sourceConfigLoading, migratingGoogleServiceAccountAuth } =
        useValues(sourceSettingsLogic)
    const { setSourceConfigValue, migrateGoogleServiceAccountAuth } = useActions(sourceSettingsLogic)

    const [jobInputs, setJobInputs] = useState<Record<string, any>>({})
    const highlightResetTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

    const highlightField = (field: HTMLElement | null): void => {
        if (!field) {
            return
        }

        field.scrollIntoView({
            behavior: 'smooth',
            block: 'center',
        })

        const highlightClasses = ['rounded-md', '!ring-2', '!ring-accent', '!ring-offset-4']
        field.classList.add(...highlightClasses)

        if (highlightResetTimeoutRef.current) {
            clearTimeout(highlightResetTimeoutRef.current)
        }
        highlightResetTimeoutRef.current = setTimeout(() => {
            field.classList.remove(...highlightClasses)
            highlightResetTimeoutRef.current = null
        }, 1800)
    }

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

    useEffect(() => {
        return () => {
            if (highlightResetTimeoutRef.current) {
                clearTimeout(highlightResetTimeoutRef.current)
            }
        }
    }, [])

    if (!sourceFieldConfig || !source) {
        return <LemonSkeleton />
    }

    const showLegacyGoogleServiceAccountAuthBanner = isGoogleServiceAccountAuthNotYetOnIntegrations(source)

    return (
        <>
            <span className="block mb-2">Overwrite your existing configuration here</span>
            {showLegacyGoogleServiceAccountAuthBanner && (
                <LemonBanner type="info" className="mb-3">
                    <div className="space-y-2">
                        <p className="mb-2">
                            {source.source_type} now uses service account credentials from Integrations. Pick an
                            existing credential below, or migrate this source&apos;s stored legacy service account key.
                            <br />
                            <br />
                            Picking an existing integration will delete the legacy service account key and a new one has
                            to be created.
                        </p>
                        <div className="flex flex-wrap items-center gap-2">
                            <LemonButton
                                size="small"
                                type="secondary"
                                onClick={() =>
                                    highlightField(document.getElementById(GOOGLE_CLOUD_CREDENTIAL_FIELD_ID))
                                }
                            >
                                Choose existing credential
                            </LemonButton>
                            <AccessControlAction
                                resourceType={AccessControlResourceType.ExternalDataSource}
                                minAccessLevel={AccessControlLevel.Editor}
                                userAccessLevel={source.user_access_level}
                            >
                                <LemonButton
                                    size="small"
                                    type="primary"
                                    loading={migratingGoogleServiceAccountAuth}
                                    onClick={() => migrateGoogleServiceAccountAuth()}
                                    data-attr="google-service-account-migrate-legacy-auth"
                                >
                                    Migrate legacy credential
                                </LemonButton>
                            </AccessControlAction>
                        </div>
                    </div>
                </LemonBanner>
            )}
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
