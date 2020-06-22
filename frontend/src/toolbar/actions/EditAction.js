import React from 'react'
import { useActions, useValues } from 'kea'
import { Button, Form, Input } from 'antd'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { ActionStepField } from '~/toolbar/actions/ActionStepField'
import { MinusCircleOutlined, SearchOutlined, PlusCircleOutlined, CloseOutlined } from '@ant-design/icons'

export function EditAction() {
    const { selectedAction, selectedActionId, inspectingElement, editingFields } = useValues(actionsTabLogic)
    const { selectAction, inspectForElementWithIndex, setEditingFields } = useActions(actionsTabLogic)

    const [form] = Form.useForm()
    const onFinish = values => {
        console.log('Received values of form: ', values)
    }
    const { getFieldValue } = form

    return (
        <div>
            <Button type="outline" size="small" onClick={() => selectAction(null)} style={{ float: 'right' }}>
                Cancel <CloseOutlined />
            </Button>
            <h1 className="section-title" style={{ paddingTop: 4 }}>
                {selectedActionId === 'new' ? 'New Action' : 'Edit Action'}
            </h1>

            <Form
                name="action_step"
                form={form}
                initialValues={selectedAction}
                onFinish={onFinish}
                fields={editingFields}
                onFieldsChange={(changedFields, allFields) => {
                    setEditingFields(allFields)
                }}
            >
                <p>What did your user do?</p>
                <Form.Item name="name" className="action-title-field">
                    <Input placeholder="E.g: Clicked Sign Up" />
                </Form.Item>
                <Form.List name="steps">
                    {(fields, { add, remove }) => (
                        <div>
                            {fields.map((field, index) => {
                                const step = getFieldValue && getFieldValue('steps')[index]
                                return (
                                    <div key={field.key} className="action-section highlight">
                                        <Button
                                            type="link"
                                            size="small"
                                            onClick={() => remove(field.name)}
                                            style={{
                                                float: 'right',
                                                padding: 0,
                                                marginTop: -5,
                                                color: 'hsl(219, 15%, 49%)',
                                            }}
                                        >
                                            Remove <MinusCircleOutlined />
                                        </Button>
                                        <h1 className="section-title">
                                            {index > 0 ? 'OR ' : null}Element #{index + 1}
                                        </h1>

                                        <div className="action-inspect">
                                            <Button
                                                size="small"
                                                type={inspectingElement === index ? 'primary' : 'outline'}
                                                onClick={() =>
                                                    inspectForElementWithIndex(
                                                        inspectingElement === index ? null : index
                                                    )
                                                }
                                            >
                                                <SearchOutlined />{' '}
                                                {step?.event === '$autocapture' ? 'Change Element' : 'Select Element'}
                                            </Button>
                                        </div>

                                        {step?.event === '$autocapture' || inspectingElement === index ? (
                                            <>
                                                <ActionStepField
                                                    field={field}
                                                    step={step}
                                                    item="href"
                                                    label="Link href"
                                                />
                                                <ActionStepField field={field} step={step} item="text" label="Text" />
                                                <ActionStepField
                                                    field={field}
                                                    step={step}
                                                    item="selector"
                                                    label="Selector"
                                                />
                                                <ActionStepField field={field} step={step} item="url" label="URL" />
                                            </>
                                        ) : null}

                                        {index === fields.length - 1 ? (
                                            <div style={{ textAlign: 'right', marginTop: 10 }}>
                                                <Button size="small" onClick={() => add()}>
                                                    Add Another Element <PlusCircleOutlined />
                                                </Button>
                                            </div>
                                        ) : null}
                                    </div>
                                )
                            })}
                            {fields.length === 0 ? (
                                <Button size="small" type="primary" onClick={() => add()}>
                                    <PlusCircleOutlined /> Add An Element
                                </Button>
                            ) : null}
                        </div>
                    )}
                </Form.List>
                <Form.Item style={{ marginTop: 20, marginBottom: 0 }}>
                    <Button type="primary" htmlType="submit">
                        {selectedActionId === 'new' ? 'Create Action' : 'Save Action'}
                    </Button>
                </Form.Item>
            </Form>
        </div>
    )
}
