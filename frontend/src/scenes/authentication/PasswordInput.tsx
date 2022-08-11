import React, { lazy, Suspense } from 'react'
import './PasswordInput.scss'
import { LemonInput } from '@posthog/lemon-ui'
import { Field } from 'lib/forms/Field'

const PasswordStrength = lazy(() => import('../../lib/components/PasswordStrength'))

interface PasswordInputProps {
    showStrengthIndicator?: boolean
    label?: string
    validateMinLength?: boolean
    validationDisabled?: boolean
    disabled?: boolean
    inputName?: string
}

export const PasswordInput = React.forwardRef(function PasswordInputInternal(
    { label = 'Password', showStrengthIndicator, disabled, inputName = 'password' }: PasswordInputProps,
    ref: React.Ref<HTMLInputElement>
): JSX.Element {
    return (
        <div className="password-input">
            <Field name={inputName} label={label}>
                {({ value, onChange }) => (
                    <>
                        {showStrengthIndicator && (
                            <Suspense fallback={<></>}>
                                <div>
                                    <PasswordStrength password={'TODO'} />
                                </div>
                            </Suspense>
                        )}
                        <LemonInput
                            type="password"
                            ref={ref}
                            className="ph-ignore-input"
                            data-attr="password"
                            placeholder="••••••••••"
                            disabled={disabled}
                            value={value}
                            onChange={onChange}
                        />
                    </>
                )}
            </Field>
        </div>
    )
})
