import { DataBeachTableType } from '~/types'
import {
    dataBeachTableFormLogic,
    DataBeachTableFormLogicProps,
    EMPTY_DATA_BEACH_FIELD,
} from './dataBeachTableFormLogic'
import { Form, Group } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'
import { useValues, useActions } from 'kea'

export interface DataBeachTableFormProps {
    dataBeachTable: DataBeachTableType | null
    onCancel: () => void
    onSave: (dataBeachTable: DataBeachTableType) => void
}

const fieldTypes = [
    { value: 'String', label: 'String' },
    { value: 'Boolean', label: 'Boolean' },
    { value: 'Integer', label: 'Integer' },
    { value: 'Float', label: 'Float' },
    { value: 'DateTime', label: 'DateTime' },
]

export function DataBeachTableForm(props: DataBeachTableFormProps): JSX.Element {
    const logicProps: DataBeachTableFormLogicProps = {
        dataBeachTable: props.dataBeachTable,
        onSave: props.onSave,
        onCancel: props.onCancel,
    }
    const logic = dataBeachTableFormLogic(logicProps)
    const { isDataBeachTableSubmitting, fields } = useValues(logic)
    const { setDataBeachTableValue } = useActions(logic)

    return (
        <Form
            logic={dataBeachTableFormLogic}
            props={logicProps}
            formKey="dataBeachTable"
            className="ant-form-vertical ant-form-hide-required-mark"
            enableFormOnSubmit // makes the HTML "submit" button work directly
        >
            <Field name="name" label="Table name">
                <LemonInput placeholder="The name of the table you'll use in your SQL queries" />
            </Field>
            <Field name="engine" label="Table engine">
                <LemonSelect options={[{ value: 'appendable', label: 'Appendable table (default)' }]} />
            </Field>
            <div>
                <table>
                    <thead>
                        <th />
                        <th>Field name</th>
                        <th>Field type</th>
                        <th />
                    </thead>
                    <tbody>
                        {fields.map((_, index) => (
                            <tr key={index}>
                                <Group name={['fields', index]}>
                                    <td>{index + 1}.</td>
                                    <td>
                                        <Field name="name">
                                            <LemonInput placeholder="Field name" />
                                        </Field>
                                    </td>
                                    <td>
                                        <Field name="type">
                                            <LemonSelect options={fieldTypes} />
                                        </Field>
                                    </td>
                                    <td>
                                        <LemonButton
                                            onClick={() => {
                                                const newFields = fields.filter((_, i) => i !== index)
                                                setDataBeachTableValue('fields', newFields)
                                            }}
                                        >
                                            Delete
                                        </LemonButton>
                                    </td>
                                </Group>
                            </tr>
                        ))}
                    </tbody>
                </table>
                <LemonButton onClick={() => setDataBeachTableValue('fields', [...fields, EMPTY_DATA_BEACH_FIELD])}>
                    Add new Field
                </LemonButton>
            </div>
            <LemonButton loading={isDataBeachTableSubmitting} htmlType="submit" type="primary">
                Save changes
            </LemonButton>
            {props.onCancel ? (
                <LemonButton onClick={props.onCancel} htmlType="button" type="secondary">
                    Cancel
                </LemonButton>
            ) : null}
        </Form>
    )
}
