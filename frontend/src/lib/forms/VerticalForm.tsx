import React from 'react'
import { BindLogic } from 'kea'
import { Form, FormProps } from 'kea-forms'
import clsx from 'clsx'

export function VerticalForm(props: FormProps): JSX.Element {
    const form = (
        <Form {...props} className={clsx('antd-form ant-form-vertical', props.className)}>
            {props.children}
        </Form>
    )
    if (props.props) {
        return (
            <BindLogic logic={props.logic} props={props.props}>
                {form}
            </BindLogic>
        )
    }
    return form
}
