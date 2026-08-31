import './VerificationCodeInput.scss'

import { OTPField } from '@base-ui/react/otp-field'
import clsx from 'clsx'
import { useId } from 'react'

import { normalizeVerificationCode } from './verificationCode'

export const VERIFICATION_CODE_LENGTH = 6

export interface VerificationCodeInputProps {
    value?: string
    onChange?: (value: string) => void
    /** Fires when all slots are filled, by typing, paste, or autofill. */
    onComplete?: (value: string) => void
    disabled?: boolean
    status?: 'default' | 'danger'
    /** LemonField injects this id to connect its label to the first slot. */
    id?: string
    'data-attr'?: string
}

export function VerificationCodeInput({
    value,
    onChange,
    onComplete,
    disabled,
    status = 'default',
    id,
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
            className={clsx(
                'VerificationCodeInput flex w-full justify-center gap-2',
                status === 'danger' && 'VerificationCodeInput--danger'
            )}
            data-attr={dataAttr}
        >
            {!id && (
                // Base UI does not accept aria-label on the first slot and expects a <label> for it.
                // When LemonField provides the id, the LemonField label already labels the first slot.
                <label htmlFor={inputId} className="sr-only">
                    Verification code
                </label>
            )}
            {Array.from({ length: VERIFICATION_CODE_LENGTH }, (_, index) => (
                <OTPField.Input
                    key={index}
                    // ph-ignore-input excludes the slots from session replay and autocapture, the same as the other auth inputs
                    className={clsx(
                        // The border colors come from VerificationCodeInput.scss. Tailwind border classes
                        // carry !important and would defeat the .Field--error override there.
                        'VerificationCodeInput__slot ph-ignore-input h-12 min-w-0 max-w-12 flex-1 rounded border bg-fill-input text-center font-mono text-2xl font-semibold leading-none text-primary caret-accent transition-colors',
                        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-highlight-secondary',
                        'disabled:cursor-not-allowed disabled:opacity-50'
                    )}
                    autoFocus={index === 0}
                    aria-label={index > 0 ? `Verification code, digit ${index + 1}` : undefined}
                />
            ))}
        </OTPField.Root>
    )
}
