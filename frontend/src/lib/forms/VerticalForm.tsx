import React from 'react'
import { Form, FormProps } from 'kea-forms'
import clsx from 'clsx'

export function VerticalForm(props: FormProps): JSX.Element {
    return (
        <Form {...props} className={clsx('antd-form ant-form-vertical', props.className)}>
            {props.children}
        </Form>
    )
}
