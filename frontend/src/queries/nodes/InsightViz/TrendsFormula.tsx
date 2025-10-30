import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { TrendsFormulaNode } from '~/queries/schema/schema-general'
import { EditorFilterProps } from '~/types'

// When updating this regex, remember to update the regex with the same name in mixins/common.py
const ALLOWED_FORMULA_CHARACTERS = /^[a-zA-Z \-*^0-9+/().]+$/

export function TrendsFormula({ insightProps }: EditorFilterProps): JSX.Element | null {
    const { formulaNodes, hasFormula } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter, removeFormulaNode } = useActions(insightVizDataLogic(insightProps))

    // Initialize with at least one empty value
    const [values, setValues] = useState<TrendsFormulaNode[]>(formulaNodes)
    const [localValues, setLocalValues] = useState<TrendsFormulaNode[]>(values)

    useEffect(() => {
        // Don't clear the formulas so that the values are still there after toggling the formula switch
        if (formulaNodes) {
            setValues(formulaNodes)
            // Merge incoming formulas with existing local fields, maintaining order
            setLocalValues((prev) => {
                const newValues = [...prev]
                // Update existing non-empty fields with backend values
                let backendIndex = 0
                for (let i = 0; i < newValues.length && backendIndex < formulaNodes.length; i++) {
                    if (newValues[i].formula.trim() !== '') {
                        newValues[i] = formulaNodes[backendIndex]
                        backendIndex++
                    }
                }
                return newValues
            })
        } else if (hasFormula) {
            // Always ensure at least one empty value when formula mode is enabled
            if (values.length === 0) {
                const emptyNode = { formula: '' }
                setValues([emptyNode])
                setLocalValues([emptyNode])
            }
        }
    }, [formulaNodes, hasFormula]) // oxlint-disable-line react-hooks/exhaustive-deps

    const updateFormulas = (newValues: TrendsFormulaNode[]): void => {
        // Filter out empty values when updating the query but keep them in local state
        const filledValues = newValues.filter((v) => v.formula.trim() !== '')
        if (filledValues.length === 0) {
            return
        }

        // Always use formulaNodes for consistency
        updateInsightFilter({
            formula: undefined,
            formulas: undefined,
            formulaNodes: filledValues,
        })
    }

    const handleFormulaChange = (index: number, value: string): void => {
        const newValues = [...localValues]
        let changedValue = value.toLocaleUpperCase()
        // Only allow typing of allowed characters
        changedValue = changedValue
            .split('')
            .filter((d) => ALLOWED_FORMULA_CHARACTERS.test(d))
            .join('')
        newValues[index] = { ...newValues[index], formula: changedValue }
        setLocalValues(newValues)
    }

    const handleCustomNameChange = (index: number, value: string): void => {
        const newValues = [...localValues]
        newValues[index] = { ...newValues[index], custom_name: value }
        setLocalValues(newValues)
    }

    const handleFormulaBlur = (index: number, e: React.FocusEvent<HTMLInputElement>): void => {
        // Ignore TrendsFormulaLabel switch click to prevent conflicting updateInsightFilter calls
        if ((e.relatedTarget as HTMLElement | undefined)?.id !== 'trends-formula-switch') {
            // Only update if the current field has content
            if (localValues[index].formula.trim() !== '') {
                updateFormulas(localValues)
            }
        }
    }

    const handleCustomNameBlur = (index: number): void => {
        // Only update if the current field has a formula with content
        if (localValues[index].formula.trim() !== '') {
            updateFormulas(localValues)
        }
    }

    const handleFormulaEnter = (): void => {
        updateFormulas(localValues)
    }

    const addFormula = (): void => {
        setLocalValues([...localValues, { formula: '' }])
    }

    const removeFormula = (index: number): void => {
        const newValues = localValues.filter((_, i) => i !== index)
        setLocalValues(newValues)

        // Delegate to Kea action to handle business logic
        removeFormulaNode(newValues)
    }

    return hasFormula ? (
        <div className="deprecated-space-y-2">
            {localValues.map((value, index) => (
                <div key={index} className="space-y-1">
                    <div className="flex items-center gap-2">
                        <LemonInput
                            className="flex-1"
                            placeholder="Example: (A + B) / 100"
                            size="small"
                            autoFocus={index === localValues.length - 1}
                            value={value.formula}
                            onChange={(value) => handleFormulaChange(index, value)}
                            onBlur={(e) => handleFormulaBlur(index, e)}
                            onPressEnter={handleFormulaEnter}
                        />
                        <LemonInput
                            className="flex-1"
                            placeholder="Formula name (optional)"
                            size="small"
                            value={value.custom_name || ''}
                            onChange={(value) => handleCustomNameChange(index, value)}
                            onBlur={() => handleCustomNameBlur(index)}
                            onPressEnter={handleFormulaEnter}
                        />
                        <LemonButton
                            icon={<IconTrash />}
                            status="alt"
                            onClick={() => removeFormula(index)}
                            title={
                                localValues.length === 1 ? 'Remove formula and disable formula mode' : 'Remove formula'
                            }
                        />
                    </div>
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
