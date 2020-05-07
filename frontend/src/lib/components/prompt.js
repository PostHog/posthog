import React from 'react'
import ReactDOM from 'react-dom'
import { Modal, Input, Form } from 'antd'

// Based on https://github.com/wangsijie/antd-prompt/blob/master/src/index.js
// Adapted for ant.design v4

function Prompt({ value, visible, afterClose, close, title, modalProps, rules, placeholder }) {
    const [form] = Form.useForm()
    const onFinish = values => {
        close(values.field)
    }

    return (
        <Modal
            {...modalProps}
            visible={visible}
            onOk={() => form.submit()}
            onCancel={() => close()}
            title={title}
            getContainer={false}
            afterClose={afterClose}
        >
            <Form form={form} name="field" initialValues={{ field: value }} onFinish={onFinish}>
                <Form.Item name="field" rules={rules}>
                    <Input placeholder={placeholder} autoFocus />
                </Form.Item>
            </Form>
        </Modal>
    )
}

export function prompt(config) {
    return new Promise((resolve, reject) => {
        const div = document.createElement('div')
        document.body.appendChild(div)
        // eslint-disable-next-line no-use-before-define
        let currentConfig = { ...config, close, visible: true }

        function destroy(value) {
            const unmountResult = ReactDOM.unmountComponentAtNode(div)
            if (unmountResult && div.parentNode) {
                div.parentNode.removeChild(div)
            }
            if (value !== undefined) {
                resolve(value)
            } else {
                reject(value)
            }
        }

        function render(props) {
            ReactDOM.render(<Prompt {...props} />, div)
        }

        function close(value) {
            currentConfig = {
                ...currentConfig,
                visible: false,
                afterClose: destroy.bind(this, value),
            }
            render(currentConfig)
        }

        render(currentConfig)
    })
}
