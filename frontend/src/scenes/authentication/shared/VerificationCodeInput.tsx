import { OTPField } from '@base-ui/react/otp-field'
import { useEffect, useRef } from 'react'

import { cn } from 'lib/utils/css-classes'

import { VERIFICATION_CODE_LENGTH, normalizeVerificationCode } from './verificationCode'

// Base UI's built-in `numeric` validation strips non-digits before our normalizer runs. That order
// would discard the fullwidth digits and separators that email clients can add to a pasted code.
// So the field opts out of the built-in validation, folds the input to ASCII first, and then keeps
// only digits.
function normalizeToDigits(value: string): string {
    return normalizeVerificationCode(value).replace(/\D/g, '')
}

export interface VerificationCodeInputProps {
    value: string
    onChange: (value: string) => void
    /** Message to show under the slots. Setting it also returns focus to the first slot. */
    error?: string | null
    disabled?: boolean
    autoFocus?: boolean
    'data-attr'?: string
}

/**
 * One slot per digit of an emailed verification code. Base UI's OTP field supplies the interaction
 * model: typing advances, backspace steps back, arrow keys move, and a paste fills all slots.
 * The field submits the owning form when the last digit arrives.
 */
export function VerificationCodeInput({
    value,
    onChange,
    error,
    disabled,
    autoFocus,
    'data-attr': dataAttr,
}: VerificationCodeInputProps): JSX.Element {
    const firstSlotRef = useRef<HTMLInputElement>(null)

    // The logic clears a rejected code, so return the cursor to the slot where the retype starts.
    // Wait until the request finishes, because a disabled slot cannot take focus.
    useEffect(() => {
        if (error && !disabled) {
            firstSlotRef.current?.focus()
        }
    }, [error, disabled])

    return (
        <div className="flex w-full flex-col gap-2" data-attr={dataAttr}>
            <OTPField.Root
                length={VERIFICATION_CODE_LENGTH}
                value={value}
                onValueChange={onChange}
                autoSubmit
                validationType="none"
                normalizeValue={normalizeToDigits}
                inputMode="numeric"
                autoComplete="one-time-code"
                disabled={disabled}
                // Codes are as sensitive as passwords, so keep them out of session recordings.
                className="ph-replay-block flex w-full items-center justify-center gap-2"
            >
                {Array.from({ length: VERIFICATION_CODE_LENGTH }, (_, index) => (
                    <OTPField.Input
                        key={index}
                        ref={index === 0 ? firstSlotRef : undefined}
                        autoFocus={autoFocus && index === 0}
                        aria-label={
                            index === 0
                                ? 'Email verification code'
                                : `Digit ${index + 1} of ${VERIFICATION_CODE_LENGTH}`
                        }
                        aria-invalid={error ? true : undefined}
                        className={cn(
                            'h-14 min-w-0 max-w-14 flex-1 rounded-md border p-0 text-center text-xl font-semibold tabular-nums',
                            'bg-surface-primary text-primary caret-accent selection:bg-accent/25 transition-colors duration-100',
                            'focus:z-10 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30',
                            'disabled:cursor-not-allowed disabled:opacity-[var(--opacity-disabled)]',
                            error
                                ? 'border-danger focus:border-danger focus:ring-danger/30'
                                : 'border-primary hover:border-secondary data-[filled]:border-secondary'
                        )}
                    />
                ))}
            </OTPField.Root>
            {error && (
                <p className="m-0 text-sm text-danger" role="alert">
                    {error}
                </p>
            )}
        </div>
    )
}
