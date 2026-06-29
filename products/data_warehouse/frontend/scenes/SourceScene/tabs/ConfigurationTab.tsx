import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect, useRef, useState } from 'react'

import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

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
    const { sourceFieldConfig, source, sourceConfigLoading, migratingGoogleServiceAccountAuth } =
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
        setSourceConfigValue(['prefix'], source.prefix ?? '')
        setSourceConfigValue(['description'], source.description ?? '')
        setJobInputs({
            ...buildKeaFormDefaultFromSourceDetails({ [source.source_type]: sourceFieldConfig })['payload'],
            ...source.job_inputs,
        })
        // `source` is updating via a poll, and so we dont't want this updating when the object reference updates but not the actual data
        // It's also the reason why it can't live in the kea logic - the selector will update on object reference changes
    }, [
        source?.access_method,
        source?.prefix,
        source?.description,
        setSourceConfigValue,
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
                    sourceConfig={sourceFieldConfig}
                    jobInputs={jobInputs}
                    initialAccessMethod={source.access_method ?? 'warehouse'}
                    setSourceConfigValue={setSourceConfigValue}
                />
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
