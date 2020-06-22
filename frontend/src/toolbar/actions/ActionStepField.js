import React from 'react'
import { Checkbox, Form, Input } from 'antd'
import { SelectorCount } from '~/toolbar/actions/SelectorCount'
import { cssEscape } from 'lib/utils/cssEscape'

export function ActionStepField({ field, step, item, label }) {
    return (
        <div className={step && step[`${item}_selected`] ? 'action-field action-field-selected' : 'action-field'}>
            <Form.Item style={{ margin: 0 }}>
                {item === 'href' && step?.href && <SelectorCount selector={`a[href="${cssEscape(step.href)}"]`} />}
                {item === 'selector' && step?.selector && <SelectorCount selector={step.selector} />}

                <Form.Item
                    name={[field.name, `${item}_selected`]}
                    fieldKey={[field.fieldKey, `${item}_selected`]}
                    valuePropName="checked"
                    noStyle
                >
                    <Checkbox>{label}</Checkbox>
                </Form.Item>
            </Form.Item>
            <Form.Item name={[field.name, item]} fieldKey={[field.fieldKey, item]}>
                {item === 'selector' ? <Input.TextArea autoSize /> : <Input />}
            </Form.Item>
        </div>
    )
}
