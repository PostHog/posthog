import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { kea, path } from 'kea'
import { Form, forms } from 'kea-forms'

import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'

import { initKeaTests } from '~/test/init'

import { LemonField } from './LemonField'

const lemonFieldTestLogic = kea<any>([
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
        expect(screen.getByText('Email').closest('label')).toHaveAttribute('for', 'email-input')
    })

    it('clicking a kea-forms label focuses the wrapped LemonInput even when the render-prop form does not pass id', () => {
        // Reproduces the dead-click pattern from the signup form (see SignupReferralSource):
        // the render-prop child only destructures `value` and `onChange`, so the underlying
        // <input> had no id and the label's `for` attribute was empty. LemonField must inject
        // a stable id onto the rendered child and use it for the label's `for`.
        render(
            <Form logic={lemonFieldTestLogic} formKey="myForm">
                <LemonField name="referral_source" label="Where did you hear about us?">
                    {({ value, onChange }) => (
                        <LemonInput value={value ?? ''} onChange={(val: string) => onChange(val)} />
                    )}
                </LemonField>
            </Form>
        )

        const label = screen.getByText('Where did you hear about us?').closest('label')
        const labelFor = label?.getAttribute('for')
        expect(labelFor).toBeTruthy()

        const input = document.querySelector('input.LemonInput__input') as HTMLInputElement | null
        expect(input).not.toBeNull()
        expect(input?.id).toBe(labelFor)
    })

    it('keeps the kea-forms id when the child is a React element (no function-as-child)', () => {
        render(
            <Form logic={lemonFieldTestLogic} formKey="myForm">
                <LemonField name="email" label="Email address">
                    <LemonInput type="email" />
                </LemonField>
            </Form>
        )

        const label = screen.getByText('Email address').closest('label')
        const labelFor = label?.getAttribute('for')
        expect(labelFor).toBeTruthy()

        const input = document.querySelector('input.LemonInput__input') as HTMLInputElement | null
        expect(input?.id).toBe(labelFor)
    })
})
