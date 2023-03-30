import { DataBeachTableType } from '~/types'
import {
    dataBeachTableFormLogic,
    DataBeachTableFormLogicProps,
    EMPTY_DATA_BEACH_FIELD,
} from './dataBeachTableFormLogic'
import { Form, Group } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonButton, LemonLabel, LemonModal, LemonSelect } from '@posthog/lemon-ui'
import { useValues, useActions } from 'kea'
import { IconDelete, IconPlus } from 'lib/lemon-ui/icons'

export interface DataBeachTableFormProps {
    title: string
    isOpen: boolean
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
    const { setDataBeachTableValue, submitDataBeachTable } = useActions(logic)

    return (
        <LemonModal
            title={props.title}
            isOpen={props.isOpen}
            onClose={props.onCancel}
            width={560}
            footer={
                <div className="flex-1 flex items-center justify-end">
                    <div className="flex items-center gap-2">
                        {props.onCancel ? (
                            <LemonButton onClick={props.onCancel} htmlType="button" type="secondary">
                                Cancel
                            </LemonButton>
                        ) : null}
                        <LemonButton
                            onClick={submitDataBeachTable}
                            loading={isDataBeachTableSubmitting}
                            htmlType="submit"
                            type="primary"
                        >
                            Save changes
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <Form
                logic={dataBeachTableFormLogic}
                props={logicProps}
                formKey="dataBeachTable"
                className="space-y-4"
                enableFormOnSubmit // makes the HTML "submit" button work directly
            >
                <Field name="name" label="Table name">
                    <LemonInput placeholder="The name of the table you'll use in your SQL queries" />
                </Field>
                <Field name="engine" label="Table engine">
                    <LemonSelect options={[{ value: 'appendable', label: 'Appendable table (default)' }]} />
                </Field>
                <div>
                    <LemonLabel className="mb-2">Fields</LemonLabel>
                    {fields.map((_, index) => (
                        <div key={index} className="w-full flex gap-2 mb-2">
                            <Group name={['fields', index]}>
                                <Field name="name">
                                    <LemonInput placeholder="Field name" className="w-60" />
                                </Field>
                                <Field name="type">
                                    <LemonSelect options={fieldTypes} />
                                </Field>
                                <div className="flex flex-1 justify-end">
                                    <LemonButton
                                        type="secondary"
                                        onClick={() => {
                                            const newFields = fields.filter((_, i) => i !== index)
                                            setDataBeachTableValue('fields', newFields)
                                        }}
                                        icon={<IconDelete />}
                                    >
                                        Delete
                                    </LemonButton>
                                </div>
                            </Group>
                        </div>
                    ))}
                    <LemonButton
                        type="secondary"
                        onClick={() => setDataBeachTableValue('fields', [...fields, EMPTY_DATA_BEACH_FIELD])}
                        icon={<IconPlus />}
                    >
                        Add Field
                    </LemonButton>
                </div>
            </Form>
        </LemonModal>
    )
}
