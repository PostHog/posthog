import React from 'react'
import { kea, path, useAllValues } from 'kea'
import { ComponentMeta } from '@storybook/react'
import { VerticalForm } from 'lib/forms/VerticalForm'
import type { formLogicType } from './Field.storiesType'
import { capitalizeFirstLetter } from 'lib/utils'
import { forms } from 'kea-forms'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { FieldV2, FieldV2Props } from './FieldV2'
import { LemonButton, LemonCheckbox } from '@posthog/lemon-ui'

export default {
    title: 'Forms/Forms',
    component: FieldV2,
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
} as ComponentMeta<typeof FieldV2>

const formLogic = kea<formLogicType>([
    path(['lib', 'forms', 'FieldV2', 'stories']),
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

export function FieldV2_(props: FieldV2Props): JSX.Element {
    const formKey = 'myForm'
    const formValues = useSpecificFormValues(formKey)
    return (
        <VerticalForm logic={formLogic} formKey={formKey} enableFormOnSubmit>
            <FieldV2 {...props} name={props.name || 'name'} label={props.label || 'Name'}>
                <LemonInput />
            </FieldV2>

            <FieldV2 {...props} name={props.name || 'email'} label={props.label || 'Email'}>
                <LemonInput />
            </FieldV2>

            <FieldV2
                {...props}
                name={props.name || 'pineappleOnPizza'}
                label={props.label || 'Pineapple on pizza preference'}
            >
                {({ value, onChange }) => (
                    <LemonCheckbox checked={value} onChange={(e) => onChange(e.target.checked)} />
                )}
            </FieldV2>

            <LemonButton
                type="primary"
                htmlType="submit"
                loading={formValues[`is${capitalizeFirstLetter(formKey)}Submitting`]}
            >
                {formValues[`is${capitalizeFirstLetter(formKey)}Submitting`] ? 'Submitting...' : 'Submit'}
            </LemonButton>
            <pre className="rounded-lg text-white bg-default p-2 m-2">
                formLogic.values = {JSON.stringify(formValues, null, 2)}
            </pre>
        </VerticalForm>
    )
}

export function TextField(props: FieldV2Props): JSX.Element {
    const formKey = 'simpleForm'
    const formValues = useSpecificFormValues(formKey)
    return (
        <VerticalForm logic={formLogic} formKey={formKey} enableFormOnSubmit>
            <FieldV2 {...props} name={props.name || 'name'} label={props.label || 'Name'}>
                <LemonInput />
            </FieldV2>
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
