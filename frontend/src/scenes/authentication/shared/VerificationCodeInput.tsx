import './VerificationCodeInput.scss'

import { OTPField } from '@base-ui/react/otp-field'
import clsx from 'clsx'
import { useId } from 'react'

import { normalizeVerificationCode } from './verificationCode'

export const VERIFICATION_CODE_LENGTH = 6

export interface VerificationCodeInputProps {
    value?: string
    onChange?: (value: string) => void
    /** Fires once every slot is filled, by typing, paste, or autofill. */
    onComplete?: (value: string) => void
    disabled?: boolean
    autoFocus?: boolean
    status?: 'default' | 'danger'
    id?: string
    'aria-label'?: string
    'data-attr'?: string
}

export function VerificationCodeInput({
    value,
    onChange,
    onComplete,
    disabled,
    autoFocus,
    status = 'default',
    id,
    'aria-label': ariaLabel,
    'data-attr': dataAttr,
}: VerificationCodeInputProps): JSX.Element {
    const generatedId = useId()
    const inputId = id ?? generatedId
    return (
        <OTPField.Root
            id={inputId}
            length={VERIFICATION_CODE_LENGTH}
            value={value}
            onValueChange={(nextValue) => onChange?.(nextValue)}
            onValueComplete={(completeValue) => onComplete?.(completeValue)}
            normalizeValue={normalizeVerificationCode}
            disabled={disabled}
            className={clsx('VerificationCodeInput', status === 'danger' && 'VerificationCodeInput--danger')}
            data-attr={dataAttr}
        >
            {ariaLabel && (
                // Base UI drops aria-label on the first slot and expects a <label> for it instead
                <label htmlFor={inputId} className="sr-only">
                    {ariaLabel}
                </label>
            )}
            {Array.from({ length: VERIFICATION_CODE_LENGTH }, (_, index) => (
                <OTPField.Input
                    key={index}
                    // Slots are excluded from session replay and autocapture like the other auth inputs
                    className="VerificationCodeInput__slot ph-ignore-input"
                    autoFocus={autoFocus && index === 0}
                    aria-label={ariaLabel && index > 0 ? `${ariaLabel}, digit ${index + 1}` : undefined}
                />
            ))}
        </OTPField.Root>
    )
}
