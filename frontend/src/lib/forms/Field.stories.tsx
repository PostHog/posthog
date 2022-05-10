import React from 'react'
import { kea, path, useAllValues } from 'kea'
import { ComponentMeta } from '@storybook/react'
import { VerticalForm } from 'lib/forms/VerticalForm'
import { Field, FieldProps } from './Field'
import type { formLogicType } from './Field.storiesType'
import { capitalizeFirstLetter } from 'lib/utils'
import { forms } from 'kea-forms'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'

export default {
    title: 'Forms/Field',
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

const formLogic = kea<formLogicType>([
    path(['lib', 'forms', 'Field', 'stories']),
    forms(({ actions }) => ({
        myForm: {
            defaults: {
                name: '',
                email: '',
                pineappleOnPizza: false,
            },
            errors: ({ name, email }) => ({
                name: !name ? 'Please enter your name' : null,
                email: !email ? 'Please enter your email' : !email.includes('@') ? 'not a valid email' : null,
            }),
            submit: async (_, breakpoint) => {
                await breakpoint(3000)
                console.log('Form Submitted')
                actions.resetMyForm()
            },
        },
        simpleForm: {
            defaults: {
                name: '',
            },
            errors: ({ name }) => ({
                name: !name ? 'Please enter your name' : undefined,
            }),
            submit: async (_, breakpoint) => {
                await breakpoint(3000)
                console.log('Form Submitted')
                actions.resetSimpleForm()
            },
        },
    })),
])

function useSpecificFormValues(formKey: string): Record<string, any> {
    const allValues = useAllValues(formLogic)
    return Object.fromEntries(
        Object.entries(allValues).filter(([key]) => key.toLowerCase().includes(formKey.toLowerCase()))
    )
}

export function Field_(props: FieldProps): JSX.Element {
    const formKey = 'myForm'
    const formValues = useSpecificFormValues(formKey)
    return (
        <VerticalForm logic={formLogic} formKey={formKey} enableFormOnSubmit>
            <Field {...props} name={props.name || 'name'} label={props.label || 'Name'}>
                <LemonInput />
            </Field>

            <Field {...props} name={props.name || 'email'} label={props.label || 'Email'}>
                <LemonInput />
            </Field>

            <Field
                {...props}
                showOptional={props.showOptional ?? true}
                name={props.name || 'pineappleOnPizza'}
                label={props.label || 'Pineapple on pizza preference'}
            >
                {({ value, onChange }) => (
                    <input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)} />
                )}
            </Field>
            <input
                type="submit"
                value={formValues[`is${capitalizeFirstLetter(formKey)}Submitting`] ? 'Submitting...' : 'Submit'}
                disabled={formValues[`is${capitalizeFirstLetter(formKey)}Submitting`]}
            />
            <pre>
                {'\n'}formLogic.values = {JSON.stringify(formValues, null, 2)}
            </pre>
        </VerticalForm>
    )
}

export function TextField(props: FieldProps): JSX.Element {
    const formKey = 'simpleForm'
    const formValues = useSpecificFormValues(formKey)
    return (
        <VerticalForm logic={formLogic} formKey={formKey} enableFormOnSubmit>
            <Field {...props} name={props.name || 'name'} label={props.label || 'Name'}>
                <LemonInput />
            </Field>
            <input
                type="submit"
                value={formValues[`is${capitalizeFirstLetter(formKey)}Submitting`] ? 'Submitting...' : 'Submit'}
                disabled={formValues[`is${capitalizeFirstLetter(formKey)}Submitting`]}
            />
            <pre>
                {'\n'}formLogic.values = {JSON.stringify(formValues, null, 2)}
            </pre>
        </VerticalForm>
    )
}
