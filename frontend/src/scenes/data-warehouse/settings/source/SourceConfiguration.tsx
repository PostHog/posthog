import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'
import { BindLogic, useValues } from 'kea'
import { Form } from 'kea-forms'
import { SourceFormComponent, SourceFormProps } from 'scenes/data-warehouse/external/forms/SourceForm'

import { dataWarehouseSourceSettingsLogic } from './dataWarehouseSourceSettingsLogic'

interface SourceConfigurationProps {
    id: string
}

export const SourceConfiguration = ({ id }: SourceConfigurationProps): JSX.Element => {
    const { sourceFieldConfig, sourceLoading } = useValues(dataWarehouseSourceSettingsLogic({ id }))
    return (
        <BindLogic logic={dataWarehouseSourceSettingsLogic} props={{ id }}>
            {sourceLoading && !sourceFieldConfig ? (
                <LemonSkeleton />
            ) : (
                <UpdateSourceConnectionFormContainer id={id} sourceConfig={sourceFieldConfig} showPrefix={false} />
            )}
        </BindLogic>
    )
}

interface UpdateSourceConnectionFormContainerProps extends SourceFormProps {
    id: string
}

function UpdateSourceConnectionFormContainer(props: UpdateSourceConnectionFormContainerProps): JSX.Element {
    const { source, sourceLoading } = useValues(dataWarehouseSourceSettingsLogic({ id: props.id }))
    return (
        <Form logic={dataWarehouseSourceSettingsLogic} formKey="sourceConfig" enableFormOnSubmit>
            <SourceFormComponent {...props} jobInputs={source?.job_inputs} />
            <div className="mt-4 flex flex-row justify-end gap-2">
                <LemonButton loading={sourceLoading} type="primary" center htmlType="submit" data-attr="source-update">
                    Save
                </LemonButton>
            </div>
        </Form>
    )
}
