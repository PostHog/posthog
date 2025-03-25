import { IconMinusSmall, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { EditorFilterProps } from '~/types'

// When updating this regex, remember to update the regex with the same name in mixins/common.py
const ALLOWED_FORMULA_CHARACTERS = /^[a-zA-Z \-*^0-9+/().]+$/

export function TrendsFormula({ insightProps }: EditorFilterProps): JSX.Element | null {
    const { formula, formulas, hasFormula } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    // Initialize with at least one empty value
    const [values, setValues] = useState<string[]>(formulas || (formula ? [formula] : ['']))
    const [localValues, setLocalValues] = useState<string[]>(values)

    useEffect(() => {
        // Don't clear the formulas so that the values are still there after toggling the formula switch
        if (formulas) {
            setValues(formulas)
            // Merge incoming formulas with existing local fields, maintaining order
            setLocalValues((prev) => {
                const newValues = [...prev]
                // Update existing non-empty fields with backend values
                let backendIndex = 0
                for (let i = 0; i < newValues.length && backendIndex < formulas.length; i++) {
                    if (newValues[i].trim() !== '') {
                        newValues[i] = formulas[backendIndex]
                        backendIndex++
                    }
                }
                return newValues
            })
        } else if (formula) {
            setValues([formula])
            // Merge single formula with existing local fields, maintaining order
            setLocalValues((prev) => {
                const newValues = [...prev]
                // Update first non-empty field with formula
                const firstNonEmptyIndex = newValues.findIndex((v) => v.trim() !== '')
                if (firstNonEmptyIndex >= 0) {
                    newValues[firstNonEmptyIndex] = formula
                }
                return newValues
            })
        } else if (hasFormula) {
            // Always ensure at least one empty value when formula mode is enabled
            if (values.length === 0) {
                setValues([''])
                setLocalValues([''])
            }
        }
    }, [formula, formulas, hasFormula])

    const updateFormulas = (newValues: string[]): void => {
        // Filter out empty values when updating the query but keep them in local state
        const filledValues = newValues.filter((v) => v.trim() !== '')
        if (filledValues.length === 0) {
            return
        }

        if (filledValues.length === 1) {
            // If there's only one formula, use the legacy formula field for backwards compatibility
            updateInsightFilter({ formula: filledValues[0], formulas: undefined })
        } else {
            // If there are multiple formulas, use the new formulas field
            updateInsightFilter({ formula: undefined, formulas: filledValues })
        }
    }

    const handleFormulaChange = (index: number, value: string): void => {
        const newValues = [...localValues]
        let changedValue = value.toLocaleUpperCase()
        // Only allow typing of allowed characters
        changedValue = changedValue
            .split('')
            .filter((d) => ALLOWED_FORMULA_CHARACTERS.test(d))
            .join('')
        newValues[index] = changedValue
        setLocalValues(newValues)
    }

    const handleFormulaBlur = (index: number, e: React.FocusEvent<HTMLInputElement>): void => {
        // Ignore TrendsFormulaLabel switch click to prevent conflicting updateInsightFilter calls
        if ((e.relatedTarget as HTMLElement | undefined)?.id !== 'trends-formula-switch') {
            // Only update if the current field has content
            if (localValues[index].trim() !== '') {
                updateFormulas(localValues)
            }
        }
    }

    const handleFormulaFocus = (): void => {
        // No longer update formulas on focus
    }

    const handleFormulaEnter = (): void => {
        updateFormulas(localValues)
    }

    const addFormula = (): void => {
        setLocalValues([...localValues, ''])
    }

    const removeFormula = (index: number): void => {
        const newValues = localValues.filter((_, i) => i !== index)
        // Always ensure at least one empty value
        if (newValues.length === 0) {
            newValues.push('')
        }
        setLocalValues(newValues)
        // Only update if there are non-empty values
        if (newValues.some((v) => v.trim() !== '')) {
            updateFormulas(newValues)
        }
    }

    return hasFormula ? (
        <div className="deprecated-space-y-2">
            {localValues.map((value, index) => (
                <div key={index} className="flex items-center gap-2">
                    <LemonInput
                        className="flex-1"
                        placeholder="Example: (A + B) / 100"
                        size="small"
                        autoFocus={index === localValues.length - 1}
                        value={value}
                        onChange={(value) => handleFormulaChange(index, value)}
                        onBlur={(e) => handleFormulaBlur(index, e)}
                        onFocus={handleFormulaFocus}
                        onPressEnter={handleFormulaEnter}
                    />
                    {localValues.length > 1 && (
                        <LemonButton
                            icon={<IconMinusSmall />}
                            status="alt"
                            onClick={() => removeFormula(index)}
                            title="Remove formula"
                        />
                    )}
                </div>
            ))}
            <div>
                <LemonButton icon={<IconPlusSmall />} type="tertiary" size="small" onClick={addFormula}>
                    Add formula
                </LemonButton>
            </div>
        </div>
    ) : null
}
