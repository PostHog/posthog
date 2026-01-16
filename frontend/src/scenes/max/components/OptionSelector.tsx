import { useEffect, useMemo, useState } from 'react'

import { LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'

import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { cn } from 'lib/utils/css-classes'

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
    const isInitialCustomAnswer = useMemo(() => {
        const valueToCheck = selectedValue ?? initialCustomValue
        return valueToCheck !== undefined && !options.some((o) => o.value === valueToCheck)
    }, [selectedValue, initialCustomValue, options])
    const [showCustomInput, setShowCustomInput] = useState(isInitialCustomAnswer)
    const [customInput, setCustomInput] = useState(initialCustomValue ?? '')
    const [selectedOption, setSelectedOption] = useState(selectedValue)

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

    const noDescriptions = options.every((o) => !o.description)

    const handleCustomSubmit = (): void => {
        if (!customInput.trim()) {
            // When not choosing a custom input, hide the input and show button again
            setShowCustomInput(false)

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
        <div
            className={cn('flex flex-col gap-1.5', {
                // When there are no descriptions, reduce the gap between options to 0.5
                'gap-0.5': noDescriptions,
            })}
        >
            <LemonRadio
                value={selectedOption}
                onChange={(value) => {
                    setSelectedOption(value)
                    setShowCustomInput(false)
                }}
                options={options.map((o) => ({
                    value: o.value,
                    label: o.label,
                    description: o.description,
                }))}
            />
            {/* {options.map((option, index) => (
                <div key={option.value} className="flex items-center gap-2">
                    <div className="text-muted size-4 shrink-0 flex items-center justify-center">{index + 1}.</div>
                    <LemonButton
                        onClick={() => onSelect(option.value)}
                        type={selectedValue === option.value ? 'secondary' : 'tertiary'}
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
            ))} */}

            {allowCustom && (
                <div className="grid items-center gap-x-2 grid-cols-[min-content_auto] text-sm">
                    {showCustomInput ? (
                        <>
                            <input type="radio" className="cursor-pointer" checked />
                            <LemonInput
                                placeholder={customPlaceholder}
                                fullWidth
                                value={customInput}
                                onChange={(newValue) => {
                                    setCustomInput(newValue)
                                    setSelectedOption('custom')
                                }}
                                onPressEnter={handleCustomSubmit}
                                autoFocus={true}
                                className="flex-grow"
                            />
                        </>
                    ) : (
                        <>
                            <input
                                type="radio"
                                className="cursor-pointer"
                                onClick={() => setShowCustomInput(!showCustomInput)}
                                checked={showCustomInput}
                                value="custom"
                            />
                            <LemonButton
                                onClick={() => setShowCustomInput(true)}
                                type="tertiary"
                                size="small"
                                className="justify-start text-tertiary flex-grow h-[37px]"
                                disabledReason={disabled ? 'Please wait' : undefined}
                            >
                                Type something...
                            </LemonButton>
                        </>
                    )}
                </div>
            )}

            <LemonButton
                type="primary"
                disabledReason={!selectedOption ? 'Please select an option' : undefined}
                onClick={() => onSelect(selectedOption ?? '')}
            >
                Next
            </LemonButton>
        </div>
    )
}
