import { LemonButton, LemonCheckbox, LemonInput, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'
import { Meta } from '@storybook/react'
import { kea, path, useAllValues } from 'kea'
import { Form, forms } from 'kea-forms'

import { Field, PureField } from './Field'
import type { formLogicType } from './Field.storiesType'

const meta: Meta<typeof PureField> = {
    title: 'Lemon UI/Forms and Fields',
    component: PureField,
    parameters: {
        docs: {
            description: {
                component: `

[Related Figma area](https://www.figma.com/file/Y9G24U4r04nEjIDGIEGuKI/PostHog-Design-System-One?node-id=3139%3A1388)

Fields are a wrapping component that take care of rendering a label, input and error messages in a standard format.

They can be used in a kea-forms controlled way via \`Field\` or a pure way via \`PureField\`.
`,
            },
        },
    },
    tags: ['autodocs'],
}
export default meta

export const _PureFields = (): JSX.Element => {
    return (
        <div className="space-y-4">
            <PureField
                label={'Text input label'}
                showOptional
                help={
                    <>
                        Optional descriptive or supportive text for the preceeding form element. This content can wrap
                        to multiple lines.
                    </>
                }
            >
                <LemonInput placeholder="Optional descriptive placeholder text" />
            </PureField>

            <PureField label={'Select label'} info={<>With info!</>}>
                <LemonSelect options={[{ value: 'foo', label: 'bar' }]} fullWidth />
            </PureField>

            <PureField label="Textarea label" error="This field has an error">
                <LemonTextArea />
            </PureField>
            <PureField>
                <LemonCheckbox bordered label="Checkbox labels are set differently" fullWidth />
            </PureField>

            <div className="flex justify-end gap-2 border-t mt-4 pt-4">
                <LemonButton type="secondary">Cancel</LemonButton>
                <LemonButton htmlType="submit" type="primary">
                    Submit
                </LemonButton>
            </div>
        </div>
    )
}

const formLogic = kea<formLogicType>([
    path(['lib', 'forms', 'Field', 'stories']),
    forms(({ actions }) => ({
        myForm: {
            defaults: {
                name: '',
                email: '',
                pineappleOnPizza: false,
            },
            errors: ({ name, email, pineappleOnPizza }) => ({
                name: !name ? 'Please enter your name' : null,
                email: !email ? 'Please enter your email' : !email.includes('@') ? 'not a valid email' : null,
                pineappleOnPizza: pineappleOnPizza ? 'I think you meant to leave this unchecked...' : null,
            }),
            submit: async (_, breakpoint) => {
                await breakpoint(3000)
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

export const _FieldsWithKeaForm = (): JSX.Element => {
    const formKey = 'myForm'
    const formValues = useSpecificFormValues(formKey)

    return (
        <Form logic={formLogic} formKey={formKey} enableFormOnSubmit>
            <div className="space-y-4">
                <Field
                    name="name"
                    label={
                        <>
                            Name <span>(What should we call you?)</span>
                        </>
                    }
                    help={
                        <>
                            Optional descriptive or supportive text for the preceeding form element. This content can
                            wrap to multiple lines.
                        </>
                    }
                >
                    <LemonInput placeholder="Jon Snow" />
                </Field>

                <Field name="select" label={'Select label'} info={<>With info!</>}>
                    <LemonSelect options={[{ value: 'foo', label: 'bar' }]} fullWidth />
                </Field>

                <Field name="email" label="Email address">
                    <LemonInput type="email" />
                </Field>
                <Field name="pineappleOnPizza">
                    <LemonCheckbox bordered label="Pineapple on your pizza?" fullWidth />
                </Field>

                <div className="flex justify-end gap-2 border-t mt-4 pt-4">
                    <LemonButton type="secondary">Cancel</LemonButton>
                    <LemonButton htmlType="submit" type="primary">
                        Submit
                    </LemonButton>
                </div>

                <pre className="rounded-lg text-white bg-default p-2 m-2">
                    formLogic.values = {JSON.stringify(formValues, null, 2)}
                </pre>
            </div>
        </Form>
    )
}
