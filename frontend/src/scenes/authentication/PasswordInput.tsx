import React, { lazy, Suspense } from 'react'
import './PasswordInput.scss'
import { LemonInput, LemonInputProps } from '@posthog/lemon-ui'

export type PasswordInputProps = LemonInputProps & {
    showStrengthIndicator?: boolean
    inputName?: string
    value?: string
}

export const PasswordInput = React.forwardRef(function PasswordInputInternal(
    { showStrengthIndicator, ...inputProps }: PasswordInputProps,
    ref: React.Ref<HTMLInputElement>
): JSX.Element {
    return (
        <div className="password-input">
            <LemonInput
                type="password"
                ref={ref}
                className="ph-ignore-input"
                data-attr="password"
                placeholder="••••••••••"
                {...inputProps}
            />
        </div>
    )
})
