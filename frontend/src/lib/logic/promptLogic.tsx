import { Form, FormItemProps, Input, InputProps, Modal, ModalProps } from 'antd'
import { actions, events, kea, key, listeners, path, props } from 'kea'
import { createRoot } from 'react-dom/client'

import type { promptLogicType } from './promptLogicType'

/**
 * This logic creates a modal to ask for an input. It's unique in that when the logic is unmounted,
 * for example when changing the URL, the modal is also closed. That would normally happen with the antd prompt.
 *
 * @deprecated Use LemonDialog or, more broadly, LemonModal instead.
 */
export const promptLogic = kea<promptLogicType>([
    path((key) => ['lib', 'logic', 'prompt', key]),
    props({} as { key: string }),
    key(({ key }) => key),

    actions({
        prompt: ({ title, placeholder, value, error, success, failure }) => ({
            title,
            placeholder,
            value,
            error,
            success,
            failure,
        }),
    }),

    events(({ cache }) => ({
        beforeUnmount: [
            () => {
                cache.runOnClose && cache.runOnClose()
            },
        ],
    })),

    listeners(({ cache }) => ({
        prompt: async ({ title, placeholder, value, error, success, failure }) => {
            const { cancel, promise } = cancellablePrompt({
                title,
                placeholder,
                value,
                rules: [
                    {
                        required: true,
                        message: error,
                    },
                ],
            })
            cache.runOnClose = cancel

            try {
                const response = await promise
                success && success(response)
            } catch (err) {
                failure && failure(err)
            }
        },
    })),
])

type PromptProps = {
    value: string
    visible: ModalProps['visible']
    afterClose: ModalProps['afterClose']
    close: ModalProps['onCancel']
    title: ModalProps['title']
    modalProps: ModalProps
    rules: FormItemProps['rules']
    placeholder: InputProps['placeholder']
}

// Based on https://github.com/wangsijie/antd-prompt/blob/master/src/index.js
// Adapted for ant.design v4 and added cancellation support
function Prompt({
    value,
    visible,
    afterClose,
    close,
    title,
    modalProps,
    rules,
    placeholder,
}: PromptProps): JSX.Element {
    const [form] = Form.useForm()
    const onFinish = (values: Record<string, any>): void => {
        close?.(values.field)
    }

    return (
        <Modal
            {...modalProps}
            visible={visible}
            onOk={form.submit}
            onCancel={close}
            title={title}
            getContainer={false}
            afterClose={afterClose}
        >
            <Form form={form} name="field" initialValues={{ field: value }} onFinish={onFinish}>
                <Form.Item name="field" rules={rules}>
                    <Input placeholder={placeholder} autoFocus data-attr="modal-prompt" />
                </Form.Item>
            </Form>
        </Modal>
    )
}

function cancellablePrompt(config: Pick<PromptProps, 'title' | 'placeholder' | 'value' | 'rules'>): {
    cancel: () => void
    promise: Promise<unknown>
} {
    let trigger = (): void => {}
    const cancel = (): void => {
        window.setTimeout(trigger, 1)
    }
    const promise = new Promise((resolve, reject) => {
        const div = document.createElement('div')
        const root = createRoot(div)
        document.body.appendChild(div)
        let currentConfig: PromptProps = { ...config, close, visible: true } as any

        function destroy(value: unknown): void {
            root.unmount()
            if (div.parentNode) {
                div.parentNode.removeChild(div)
            }
            if (typeof value === 'string') {
                resolve(value)
            } else {
                reject(value)
            }
        }

        function render(props: PromptProps): void {
            root.render(<Prompt {...props} />)
        }

        function close(this: PromptProps, value: string): void {
            currentConfig = {
                ...currentConfig,
                visible: false,
                afterClose: destroy.bind(this, value),
            }
            render(currentConfig)
        }

        trigger = close as any

        render(currentConfig)
    })

    return {
        cancel,
        promise,
    }
}
