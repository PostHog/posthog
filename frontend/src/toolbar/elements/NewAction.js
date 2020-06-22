import React, { useRef } from 'react'
import { cssEscape } from 'lib/utils/cssEscape'
import { Input, Form, Checkbox } from 'antd'

export function SelectorCount({ selector }) {
    let selectorError = false
    let matches

    if (selector) {
        try {
            matches = document.querySelectorAll(selector).length
        } catch {
            selectorError = true
        }
    }
    return (
        <small style={{ float: 'right', color: selectorError ? 'red' : '' }}>
            {selectorError ? 'Invalid selector' : `Matches ${matches} elements`}
        </small>
    )
}

export function ActionField({ item, label, getFieldValue }) {
    let selector = null

    if (getFieldValue) {
        if (item === 'href' && getFieldValue('href')) {
            selector = `a[href="${cssEscape(getFieldValue('href'))}"]`
        }
        if (item === 'selector' && getFieldValue('selector')) {
            selector = getFieldValue('selector')
        }
    }

    return (
        <div
            className={
                getFieldValue && getFieldValue(`${item}_selected`)
                    ? 'action-field action-field-selected'
                    : 'action-field'
            }
        >
            <Form.Item style={{ margin: 0 }}>
                {selector && <SelectorCount selector={selector} />}

                <Form.Item name={`${item}_selected`} valuePropName="checked" noStyle>
                    <Checkbox>{label}</Checkbox>
                </Form.Item>
            </Form.Item>
            <Form.Item name={item}>{item === 'selector' ? <Input.TextArea autoSize /> : <Input />}</Form.Item>
        </div>
    )
}

export function NewAction({ actionStep }) {
    const formRef = useRef()
    const onFinish = values => {
        console.log('Received values of form: ', values)
    }
    const { getFieldValue } = formRef.current || {}

    return (
        <Form name="action_step" ref={formRef} initialValues={actionStep} onFinish={onFinish}>
            <p>Add new action for the selected element!</p>
            <Form.Item name="title" className="action-title-field">
                <Input placeholder="For example: user signed up" />
            </Form.Item>

            <ActionField getFieldValue={getFieldValue} actionStep={actionStep} item="href" label="Link href" />
            <ActionField getFieldValue={getFieldValue} actionStep={actionStep} item="text" label="Text" />
            <ActionField getFieldValue={getFieldValue} actionStep={actionStep} item="selector" label="Selector" />
            <ActionField getFieldValue={getFieldValue} actionStep={actionStep} item="url" label="URL" />
        </Form>
    )
}
