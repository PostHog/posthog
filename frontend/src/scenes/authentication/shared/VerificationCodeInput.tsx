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
    status?: 'default' | 'danger'
    /** Injected by LemonField to associate its label with the first slot. */
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
                // Base UI drops aria-label on the first slot and expects a <label> for it instead.
                // When LemonField provides the id, its own visible label already fills that role.
                <label htmlFor={inputId} className="sr-only">
                    Verification code
                </label>
            )}
            {Array.from({ length: VERIFICATION_CODE_LENGTH }, (_, index) => (
                <OTPField.Input
                    key={index}
                    // ph-ignore-input excludes the slots from session replay and autocapture like the other auth inputs
                    className={clsx(
                        // Border color and its states live in VerificationCodeInput.scss: the .Field--error
                        // override could not beat Tailwind's !important border utilities from there
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
