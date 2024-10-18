import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'
import { BindLogic, useValues } from 'kea'
import { Form } from 'kea-forms'
import { SourceFormComponent, SourceFormProps } from 'scenes/data-warehouse/external/forms/SourceForm'

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

function UpdateSourceConnectionFormContainer(props: UpdateSourceConnectionFormContainerProps): JSX.Element {
    const { source, sourceLoading } = useValues(dataWarehouseSourceSettingsLogic({ id: props.id }))

    if (source?.source_type !== 'MSSQL' && source?.source_type !== 'MySQL' && source?.source_type !== 'Postgres') {
        return (
            <LemonBanner type="warning" className="mt-2">
                <p>
                    Only Postgres, MSSQL, and MySQL are configurable. Please delete and recreate your source if you need
                    to connect to a new source of the same type.
                </p>
            </LemonBanner>
        )
    }
    return (
        <Form logic={dataWarehouseSourceSettingsLogic} formKey="sourceConfig" enableFormOnSubmit>
            <SourceFormComponent {...props} jobInputs={source?.job_inputs} />
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
    )
}
