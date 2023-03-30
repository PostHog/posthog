import { DataBeachTableType } from '~/types'
import { dataBeachIngestionFormLogic, DataBeachIngestionFormLogicProps } from './dataBeachIngestionFormLogic'
import { Form, Group } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { LemonButton, LemonModal, LemonInput } from '@posthog/lemon-ui'
import { useValues, useActions } from 'kea'
import { IconDelete, IconPlus } from 'lib/lemon-ui/icons'

export interface DataBeachIngestionFormProps {
    isOpen: boolean
    dataBeachTable?: DataBeachTableType | null
    onClose: () => void
}

export function DataBeachIngestionForm(props: DataBeachIngestionFormProps): JSX.Element {
    const logicProps: DataBeachIngestionFormLogicProps = {
        dataBeachTable: props.dataBeachTable ?? null,
        onClose: props.onClose,
    }
    const logic = dataBeachIngestionFormLogic(logicProps)
    const { isIngestionFormSubmitting, rows, fields } = useValues(logic)
    const { setIngestionFormValue, submitIngestionForm } = useActions(logic)

    return (
        <LemonModal
            title={`Insert data into ${props.dataBeachTable?.name ?? ''}`}
            isOpen={props.isOpen}
            onClose={props.onClose}
            width={'90%'}
            footer={
                <div className="flex-1 flex items-center justify-end">
                    <div className="flex items-center gap-2">
                        {props.onClose ? (
                            <LemonButton onClick={props.onClose} htmlType="button" type="secondary">
                                Close
                            </LemonButton>
                        ) : null}
                        <LemonButton
                            loading={isIngestionFormSubmitting}
                            onClick={submitIngestionForm}
                            htmlType="submit"
                            type="primary"
                        >
                            Insert rows
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <Form
                logic={dataBeachIngestionFormLogic}
                props={logicProps}
                formKey="ingestionForm"
                className="space-y-4"
                enableFormOnSubmit // makes the HTML "submit" button work directly
            >
                {rows.map((_, index) => (
                    <div key={index} className="w-full flex gap-2 mb-2">
                        <Group name={['rows', index]}>
                            <div className="flex items-start">
                                {/* eslint-disable-next-line react/forbid-dom-props */}
                                <div style={{ lineHeight: '40px' }}>{index + 1}.</div>
                            </div>
                            <div className="flex flex-wrap items-center gap-2">
                                {fields.map((field) => (
                                    <Field key={field.name} name={field.name}>
                                        <LemonInput placeholder={field.name} />
                                    </Field>
                                ))}
                            </div>
                            <div className="flex flex-1 items-start justify-end">
                                <LemonButton
                                    type="secondary"
                                    onClick={() => {
                                        const newRows = rows.filter((_, i) => i !== index)
                                        setIngestionFormValue('rows', newRows)
                                    }}
                                    icon={<IconDelete />}
                                />
                            </div>
                        </Group>
                    </div>
                ))}
                <LemonButton
                    type="secondary"
                    onClick={() => setIngestionFormValue('rows', [...rows, {}])}
                    icon={<IconPlus />}
                >
                    Add Row
                </LemonButton>
            </Form>
        </LemonModal>
    )
}
