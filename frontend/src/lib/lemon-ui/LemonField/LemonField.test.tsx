import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { kea, path } from 'kea'
import { Form, forms } from 'kea-forms'

import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'

import { initKeaTests } from '~/test/init'

import { LemonField } from './LemonField'
import type { lemonFieldTestLogicType } from './LemonField.testType'

const lemonFieldTestLogic = kea<lemonFieldTestLogicType>([
    path(['lib', 'lemon-ui', 'LemonField', 'test']),
    forms(() => ({
        myForm: {
            defaults: { referral_source: '', email: '' } as { referral_source: string; email: string },
            errors: () => ({}),
            submit: () => {},
        },
    })),
])

describe('LemonField', () => {
    beforeEach(() => {
        initKeaTests()
        lemonFieldTestLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    it('Pure field wires the explicit htmlFor onto the label', () => {
        render(
            <LemonField.Pure label="Email" htmlFor="email-input">
                <input id="email-input" />
            </LemonField.Pure>
        )

        // getByLabelText only resolves when the label is correctly associated with the input,
        // so it's both the assertion and the proof of correct wiring.
        expect(screen.getByLabelText('Email')).toBe(document.getElementById('email-input'))
    })

    it.each([
        {
            desc: 'function-as-child render prop (the signup dead-click pattern)',
            label: 'Where did you hear about us?',
            field: (
                <LemonField name="referral_source" label="Where did you hear about us?">
                    {({ value, onChange }) => (
                        <LemonInput value={value ?? ''} onChange={(val: string) => onChange(val)} />
                    )}
                </LemonField>
            ),
        },
        {
            desc: 'React-element child (no render prop)',
            label: 'Email address',
            field: (
                <LemonField name="email" label="Email address">
                    <LemonInput type="email" />
                </LemonField>
            ),
        },
    ])('clicking the label focuses the wrapped input — $desc', ({ label, field }) => {
        render(
            <Form logic={lemonFieldTestLogic} formKey="myForm">
                {field}
            </Form>
        )

        // getByLabelText only finds the input when label[for] matches input[id].
        // If LemonField regressed to emitting htmlFor={undefined}, this throws.
        const input = screen.getByLabelText(label) as HTMLInputElement
        expect(input).toBeInstanceOf(HTMLInputElement)
        expect(input.id).toBeTruthy()
        expect(screen.getByText(label).closest('label')?.getAttribute('for')).toBe(input.id)
    })
})
