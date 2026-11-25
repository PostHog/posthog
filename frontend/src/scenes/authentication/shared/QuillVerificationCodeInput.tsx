import { OTPField } from '@base-ui/react/otp-field'

import { cn } from '@posthog/quill'

import { normalizeVerificationCode } from './verificationCode'

export function QuillVerificationCodeInput({
    inputId,
    labelled,
    length,
    value,
    onChange,
    onComplete,
    disabled,
    invalid,
    'data-attr': dataAttr,
}: {
    inputId: string
    /** Whether a field label outside already labels the first slot. */
    labelled: boolean
    length: number
    value?: string
    onChange?: (value: string) => void
    onComplete?: (value: string) => void
    disabled?: boolean
    invalid: boolean
    'data-attr'?: string
}): JSX.Element {
    return (
        <OTPField.Root
            id={inputId}
            length={length}
            value={value}
            onValueChange={(nextValue) => onChange?.(nextValue)}
            onValueComplete={(completeValue) => onComplete?.(completeValue)}
            normalizeValue={normalizeVerificationCode}
            disabled={disabled}
            data-quill
            className="flex w-full justify-center gap-2"
            data-attr={dataAttr}
        >
            {!labelled && (
                <label htmlFor={inputId} className="sr-only">
                    Verification code
                </label>
            )}
            {Array.from({ length }, (_, index) => (
                <OTPField.Input
                    key={index}
                    // ph-ignore-input excludes the slots from session replay and autocapture, the same as the other auth inputs
                    className={cn(
                        'ph-ignore-input h-12 min-w-0 max-w-12 flex-1 rounded-sm border bg-transparent text-center font-mono text-2xl font-semibold leading-none text-foreground transition-colors',
                        'border-input focus-visible:outline-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-50'
                    )}
                    // The bridge registers no destructive border utility, so the error border reads the token directly.
                    // eslint-disable-next-line react/forbid-dom-props
                    style={invalid ? { borderColor: 'var(--destructive-foreground)' } : undefined}
                    autoFocus={index === 0}
                    aria-invalid={invalid || undefined}
                    aria-label={index > 0 ? `Verification code, digit ${index + 1}` : undefined}
                />
            ))}
        </OTPField.Root>
    )
}
