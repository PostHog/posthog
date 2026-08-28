import { OTPField } from '@base-ui/react/otp-field'
import { useEffect, useRef } from 'react'

import { cn } from 'lib/utils/css-classes'

import { normalizeVerificationCode } from './verificationCode'

export const VERIFICATION_CODE_LENGTH = 6

// Base UI's built-in `numeric` validation strips everything `\d` rejects *before* our normalizer
// runs, which would throw away the fullwidth digits and separators an email client can hand us on
// paste. So we opt out of its validation and normalize ourselves: fold to ASCII first, keep digits.
function normalizeToDigits(value: string): string {
    return normalizeVerificationCode(value).replace(/\D/g, '')
}

export interface VerificationCodeInputProps {
    value: string
    onChange: (value: string) => void
    /** Fired once all slots are filled, by typing or paste — wire this to submit. */
    onComplete?: (value: string) => void
    /** Message to show under the slots. Setting it also returns focus to the first slot. */
    error?: string | null
    disabled?: boolean
    autoFocus?: boolean
    label?: string
    'data-attr'?: string
    className?: string
}

/**
 * One slot per digit of an emailed verification code, on top of Base UI's OTP field — which is what
 * gives us auto-advance, backspace-to-previous, arrow keys, and paste-anywhere-fills-everything.
 */
export function VerificationCodeInput({
    value,
    onChange,
    onComplete,
    error,
    disabled,
    autoFocus,
    label = 'Email verification code',
    'data-attr': dataAttr,
    className,
}: VerificationCodeInputProps): JSX.Element {
    const firstSlotRef = useRef<HTMLInputElement>(null)

    // A rejected code is cleared by the logic, so put the cursor back where the retype starts. Wait
    // for the request to finish: a disabled slot cannot take focus.
    useEffect(() => {
        if (error && !disabled) {
            firstSlotRef.current?.focus()
        }
    }, [error, disabled])

    return (
        <div className={cn('flex w-full flex-col gap-2', className)} data-attr={dataAttr}>
            <OTPField.Root
                length={VERIFICATION_CODE_LENGTH}
                value={value}
                onValueChange={onChange}
                onValueComplete={(completed) => onComplete?.(completed)}
                validationType="none"
                normalizeValue={normalizeToDigits}
                inputMode="numeric"
                autoComplete="one-time-code"
                disabled={disabled}
                // Codes are as sensitive as passwords — keep them out of session recordings.
                className="ph-replay-block flex w-full items-center justify-center gap-2"
            >
                {Array.from({ length: VERIFICATION_CODE_LENGTH }, (_, index) => (
                    <OTPField.Input
                        key={index}
                        ref={index === 0 ? firstSlotRef : undefined}
                        autoFocus={autoFocus && index === 0}
                        aria-label={index === 0 ? label : `Digit ${index + 1} of ${VERIFICATION_CODE_LENGTH}`}
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
