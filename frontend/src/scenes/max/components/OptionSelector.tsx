import { useEffect, useState } from 'react'

import { LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'

export interface Option {
    label: string
    value: string
    icon?: JSX.Element
    description?: string
}

interface OptionSelectorProps {
    options: Option[]
    onSelect: (value: string) => void
    allowCustom?: boolean
    customPlaceholder?: string
    onCustomSubmit?: (value: string) => void
    disabled?: boolean
    loading?: boolean
    loadingMessage?: string
    /** Initial value for the custom input (used when editing a previous answer) */
    initialCustomValue?: string
    /** Currently selected value (used to highlight the selected option) */
    selectedValue?: string
}

export function OptionSelector({
    options,
    onSelect,
    allowCustom = false,
    customPlaceholder = 'Type your response...',
    onCustomSubmit,
    disabled = false,
    loading = false,
    loadingMessage = 'Processing...',
    initialCustomValue,
    selectedValue,
}: OptionSelectorProps): JSX.Element {
    const isInitialCustomAnswer =
        initialCustomValue !== undefined && !options.some((o) => o.value === initialCustomValue)
    const [showCustomInput, setShowCustomInput] = useState(isInitialCustomAnswer)
    const [customInput, setCustomInput] = useState(initialCustomValue ?? '')

    useEffect(() => {
        if (disabled || loading) {
            return
        }

        function handleKeyDown(event: KeyboardEvent): void {
            if (showCustomInput && event.key === 'Escape') {
                event.preventDefault()
                setShowCustomInput(false)
                setCustomInput('')
                return
            }

            // Don't trigger keyboard shortcuts when typing in an input
            if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) {
                return
            }

            for (const [index, option] of options.entries()) {
                if (event.key === String(index + 1)) {
                    event.preventDefault()
                    onSelect(option.value)
                    return
                }
            }

            if (allowCustom && event.key === String(options.length + 1)) {
                event.preventDefault()
                setShowCustomInput(true)
            }
        }

        window.addEventListener('keydown', handleKeyDown)
        return () => {
            window.removeEventListener('keydown', handleKeyDown)
        }
    }, [options, onSelect, allowCustom, disabled, loading, showCustomInput])

    const handleCustomSubmit = (): void => {
        if (!customInput.trim()) {
            return
        }
        onCustomSubmit?.(customInput.trim())
    }

    if (loading) {
        return (
            <div className="flex items-center gap-2 text-muted">
                <Spinner className="size-4" />
                <span>{loadingMessage}</span>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-1.5">
            {options.map((option, index) => (
                <div key={option.value} className="flex items-center gap-2">
                    <div className="text-muted size-4 shrink-0 flex items-center justify-center">{index + 1}.</div>
                    <LemonButton
                        onClick={() => onSelect(option.value)}
                        type={selectedValue === option.value ? 'primary' : 'secondary'}
                        size="small"
                        icon={option.icon}
                        className="justify-start text-wrap flex-grow"
                        disabledReason={disabled ? 'Please wait' : undefined}
                    >
                        <span className="flex flex-col gap-1">
                            <span className="font-medium">{option.label}</span>
                            {option.description && <span className="text-xs text-secondary">{option.description}</span>}
                        </span>
                    </LemonButton>
                </div>
            ))}

            {allowCustom && (
                <div className="flex items-center gap-2">
                    <div className="text-muted size-4 shrink-0 flex items-center justify-center">
                        {options.length + 1}.
                    </div>
                    {showCustomInput ? (
                        <>
                            <LemonInput
                                placeholder={customPlaceholder}
                                fullWidth
                                value={customInput}
                                onChange={(newValue) => setCustomInput(newValue)}
                                onPressEnter={handleCustomSubmit}
                                autoFocus
                                className="flex-grow"
                            />
                            <LemonButton
                                type="primary"
                                onClick={handleCustomSubmit}
                                disabledReason={!customInput.trim() ? 'Please type a response' : undefined}
                            >
                                Submit
                            </LemonButton>
                        </>
                    ) : (
                        <LemonButton
                            onClick={() => setShowCustomInput(true)}
                            type="tertiary"
                            size="small"
                            className="justify-start text-muted flex-grow"
                            disabledReason={disabled ? 'Please wait' : undefined}
                        >
                            Type something...
                        </LemonButton>
                    )}
                </div>
            )}
        </div>
    )
}
