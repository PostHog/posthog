import React from 'react'
import { kea, useValues } from 'kea'
import { ComponentMeta } from '@storybook/react'

import { VerticalForm } from 'lib/forms/VerticalForm'
import { Field, FieldProps } from './Field'
import type { formLogicType } from './Field.storiesType'

export default {
    title: 'Forms-Core/Field',
    component: Field,
    argTypes: {
        name: {
            control: { type: 'text' },
            description: 'Key of field in the form',
            type: 'string',
        },
        label: {
            control: { type: 'text' },
            description: 'Text that appears above the field',
            type: 'string',
        },
        hint: {
            control: { type: 'text' },
            description: 'Text that appears below the field',
            type: 'string',
        },
        noStyle: {
            control: { type: 'boolean' },
            description: 'Directly return `children` without labels, errors, etc.',
        },
        children: {
            description: 'The component to render',
        },
        template: {
            description: 'Form template to use (WIP)',
        },
    },
} as ComponentMeta<typeof Field>

const formLogic = kea<formLogicType>({
    path: ['lib', 'forms', 'Field', 'stories'],
    forms: {
        myForm: {
            defaults: {
                name: '',
                email: '',
                pineappleOnPizza: false,
            },
        },
    },
})

export function Field_(props: FieldProps): JSX.Element {
    const { myForm } = useValues(formLogic)
    return (
        <VerticalForm logic={formLogic} formKey="myForm">
            <Field {...props} name={props.name || 'name'} label={props.label || 'Name'}>
                <input />
            </Field>

            <Field {...props} name={props.name || 'email'} label={props.label || 'Email'}>
                <input />
            </Field>

            <Field
                {...props}
                showOptional={props.showOptional ?? true}
                name={props.name || 'pineappleOnPizza'}
                label={props.label || 'Pineapple on pizza preference'}
            >
                <input />
            </Field>

            <pre>{JSON.stringify(myForm, null, 2)}</pre>
        </VerticalForm>
    )
}
