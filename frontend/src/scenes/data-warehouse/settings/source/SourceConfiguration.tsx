import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { SourceFormComponent, SourceFormProps } from 'scenes/data-warehouse/external/forms/SourceForm'

import { ExternalDataSourceType } from '~/types'

import { dataWarehouseSourceSettingsLogic } from './dataWarehouseSourceSettingsLogic'

interface SourceConfigurationProps {
    id: string
}

export const SourceConfiguration = ({ id }: SourceConfigurationProps): JSX.Element => {
    const { sourceFieldConfig } = useValues(dataWarehouseSourceSettingsLogic({ id }))
    return (
        <BindLogic logic={dataWarehouseSourceSettingsLogic} props={{ id }}>
            {sourceFieldConfig ? (
                <UpdateSourceConnectionFormContainer id={id} sourceConfig={sourceFieldConfig} showPrefix={false} />
            ) : (
                <LemonSkeleton />
            )}
        </BindLogic>
    )
}

interface UpdateSourceConnectionFormContainerProps extends SourceFormProps {
    id: string
}

const supportedEditingSourceTypes: ExternalDataSourceType[] = ['MSSQL', 'MySQL', 'Postgres', 'Stripe']

function UpdateSourceConnectionFormContainer(props: UpdateSourceConnectionFormContainerProps): JSX.Element {
    const { source, sourceLoading } = useValues(dataWarehouseSourceSettingsLogic({ id: props.id }))
    const { setSourceConfigValue } = useActions(dataWarehouseSourceSettingsLogic)

    if (!source?.source_type || !supportedEditingSourceTypes.includes(source?.source_type)) {
        return (
            <LemonBanner type="warning" className="mt-2">
                <p>
                    Only {supportedEditingSourceTypes.slice(0, -1).join(', ')}, and {supportedEditingSourceTypes.at(-1)}{' '}
                    are configurable. Please delete and recreate your source if you need to connect to a new source of
                    the same type.
                </p>
            </LemonBanner>
        )
    }

    return (
        <>
            <span className="block mb-2">Overwrite your existing configuration here</span>
            <Form logic={dataWarehouseSourceSettingsLogic} formKey="sourceConfig" enableFormOnSubmit>
                <SourceFormComponent
                    {...props}
                    jobInputs={source?.job_inputs}
                    setSourceConfigValue={setSourceConfigValue}
                />
                <div className="mt-4 flex flex-row justify-end gap-2">
                    <LemonButton
                        loading={sourceLoading && !source}
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
