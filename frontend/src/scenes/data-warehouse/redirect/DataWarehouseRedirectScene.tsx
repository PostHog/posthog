import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { sourceFormLogic } from 'scenes/data-warehouse/external/forms/sourceFormLogic'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: DataWarehouseRedirectScene,
    logic: sourceFormLogic,
}

export function DataWarehouseRedirectScene(): JSX.Element {
    return (
        <div className="text-left flex flex-col">
            <h2>Configure</h2>
            <p>Add a prefix to your tables to avoid conflicts with other data sources</p>
            <Form
                logic={sourceFormLogic}
                formKey="externalDataSource"
                className="space-y-4 max-w-100"
                enableFormOnSubmit
            >
                <Field name="prefix" label="Table prefix">
                    <LemonInput />
                </Field>
                <LemonButton type="primary" htmlType="submit">
                    Submit
                </LemonButton>
            </Form>
        </div>
    )
}

export default DataWarehouseRedirectScene
