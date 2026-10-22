import './VerificationCodeInput.scss'

import clsx from 'clsx'
import { useId, useState } from 'react'

import { normalizeVerificationCode } from './verificationCode'

export const VERIFICATION_CODE_LENGTH = 6

export interface VerificationCodeInputProps {
    value?: string
    onChange?: (value: string) => void
    /** Fires when all slots are filled, by typing, paste, or autofill. */
    onComplete?: (value: string) => void
    disabled?: boolean
    status?: 'default' | 'danger'
    /** LemonField injects this id to connect its label to the input. */
    id?: string
    'data-attr'?: string
}

function toCode(raw: string): string {
    return normalizeVerificationCode(raw).replace(/\D/g, '').slice(0, VERIFICATION_CODE_LENGTH)
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
    const [uncontrolledCode, setUncontrolledCode] = useState('')
    const [focused, setFocused] = useState(false)
    const code = toCode(value ?? uncontrolledCode)
    const activeIndex = Math.min(code.length, VERIFICATION_CODE_LENGTH - 1)

    const commit = (nextCode: string, fromPaste: boolean): void => {
        if (nextCode !== code) {
            setUncontrolledCode(nextCode)
            onChange?.(nextCode)
        }
        if (nextCode.length === VERIFICATION_CODE_LENGTH && (code.length !== VERIFICATION_CODE_LENGTH || fromPaste)) {
            onComplete?.(nextCode)
        }
    }

    return (
        <div
            className={clsx(
                'VerificationCodeInput relative flex w-full justify-center gap-2',
                status === 'danger' && 'VerificationCodeInput--danger',
                disabled && 'VerificationCodeInput--disabled'
            )}
            data-attr={dataAttr}
        >
            {!id && (
                // When LemonField provides the id, the LemonField label already labels the input
                <label htmlFor={inputId} className="sr-only">
                    Verification code
                </label>
            )}
            {/* The digits render here as text, so ph-no-capture keeps them out of session replay */}
            {Array.from({ length: VERIFICATION_CODE_LENGTH }, (_, index) => (
                <div
                    key={index}
                    aria-hidden
                    className="VerificationCodeInput__slot ph-no-capture flex h-12 min-w-0 max-w-12 flex-1 items-center justify-center rounded border bg-fill-input font-mono text-2xl font-semibold leading-none text-primary transition-colors"
                    data-active={focused && index === activeIndex ? '' : undefined}
                >
                    {code[index] ??
                        (focused && index === activeIndex ? <span className="VerificationCodeInput__caret" /> : null)}
                </div>
            ))}
            {/* One input spans all the slots. Focus never moves between elements, so a mobile keyboard
                stays open while the user types, and one-time-code autofill fills the whole code. */}
            <input
                id={inputId}
                // ph-ignore-input excludes the input from session replay and autocapture, the same as the other auth inputs
                className="VerificationCodeInput__input ph-ignore-input absolute inset-0 h-full w-full border-0 bg-transparent font-mono text-2xl text-transparent caret-transparent outline-none selection:bg-transparent disabled:cursor-not-allowed"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                autoCorrect="off"
                spellCheck={false}
                enterKeyHint="done"
                value={code}
                disabled={disabled}
                autoFocus
                onFocus={() => setFocused(true)}
                onBlur={() => setFocused(false)}
                onChange={(event) => commit(toCode(event.currentTarget.value), false)}
                onPaste={(event) => {
                    const pastedCode = toCode(event.clipboardData.getData('text/plain'))
                    // A full code replaces the current one, wherever the caret is
                    if (pastedCode.length === VERIFICATION_CODE_LENGTH) {
                        event.preventDefault()
                        commit(pastedCode, true)
                    }
                }}
            />
        </div>
    )
}
