import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect, useState } from 'react'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { SourceFormComponent } from 'products/data_warehouse/frontend/shared/components/forms/SourceForm'

import { availableSourcesLogic } from '../../NewSourceScene/availableSourcesLogic'
import { buildKeaFormDefaultFromSourceDetails } from '../../NewSourceScene/sourceWizardLogic'
import { sourceSettingsLogic } from './sourceSettingsLogic'

interface ConfigurationTabProps {
    id: string
}

export const ConfigurationTab = ({ id }: ConfigurationTabProps): JSX.Element => {
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesLogic)

    if (availableSourcesLoading || availableSources === null) {
        return <LemonSkeleton />
    }

    return (
        <BindLogic logic={sourceSettingsLogic} props={{ id, availableSources }}>
            <UpdateSourceConnectionFormContainer />
        </BindLogic>
    )
}

function UpdateSourceConnectionFormContainer(): JSX.Element {
    const { sourceFieldConfig, source, sourceConfigLoading } = useValues(sourceSettingsLogic)
    const { setSourceConfigValue } = useActions(sourceSettingsLogic)

    const [jobInputs, setJobInputs] = useState<Record<string, any>>({})

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
                    sourceConfig={sourceFieldConfig}
                    jobInputs={jobInputs}
                    initialAccessMethod={source.access_method ?? 'warehouse'}
                    setSourceConfigValue={setSourceConfigValue}
                />
                <div className="mt-4 flex flex-row justify-end gap-2">
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
        </>
    )
}
