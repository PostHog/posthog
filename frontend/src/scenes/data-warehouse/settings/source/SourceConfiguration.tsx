import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect, useState } from 'react'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { SourceFormComponent } from 'scenes/data-warehouse/external/forms/SourceForm'
import { availableSourcesDataLogic } from 'scenes/data-warehouse/new/availableSourcesDataLogic'
import { buildKeaFormDefaultFromSourceDetails } from 'scenes/data-warehouse/new/sourceWizardLogic'

import { dataWarehouseSourceSettingsLogic } from './dataWarehouseSourceSettingsLogic'

interface SourceConfigurationProps {
    id: string
}

export const SourceConfiguration = ({ id }: SourceConfigurationProps): JSX.Element => {
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesDataLogic)

    if (availableSourcesLoading || availableSources === null) {
        return <LemonSkeleton />
    }

    return (
        <BindLogic logic={dataWarehouseSourceSettingsLogic} props={{ id, availableSources }}>
            <UpdateSourceConnectionFormContainer />
        </BindLogic>
    )
}

function UpdateSourceConnectionFormContainer(): JSX.Element {
    const { sourceFieldConfig, source, sourceConfigLoading } = useValues(dataWarehouseSourceSettingsLogic)
    const { setSourceConfigValue } = useActions(dataWarehouseSourceSettingsLogic)

    const [jobInputs, setJobInputs] = useState<Record<string, any>>({})

    useEffect(() => {
        if (!source || !sourceFieldConfig) {
            return
        }

        setJobInputs({
            ...buildKeaFormDefaultFromSourceDetails({ [source.source_type]: sourceFieldConfig })['payload'],
            ...source.job_inputs,
        })
        // `source` is updating via a poll, and so we dont't want this updating when the object reference updates but not the actual data
        // It's also the reason why it can't live in the kea logic - the selector will update on object reference changes
    }, [
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
            <Form logic={dataWarehouseSourceSettingsLogic} formKey="sourceConfig" enableFormOnSubmit>
                <SourceFormComponent
                    showPrefix={false}
                    sourceConfig={sourceFieldConfig}
                    jobInputs={jobInputs}
                    setSourceConfigValue={setSourceConfigValue}
                />
                <div className="mt-4 flex flex-row justify-end gap-2">
                    <LemonButton
                        loading={sourceConfigLoading}
                        type="primary"
                        center
                        htmlType="submit"
                        data-attr="source-update"
                    >
                        Save
                    </LemonButton>
                </div>
            </Form>
        </>
    )
}
