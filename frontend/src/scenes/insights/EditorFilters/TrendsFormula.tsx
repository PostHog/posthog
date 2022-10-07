import React, { useEffect, useState } from 'react'
import { EditorFilterProps } from '~/types'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { LemonInput, LemonSwitch } from '@posthog/lemon-ui'

// When updating this regex, remember to update the regex with the same name in mixins/common.py
const ALLOWED_FORMULA_CHARACTERS = /^[a-zA-Z\ \-\*\^0-9\+\/\(\)\.]+$/

export function TrendsFormula({ filters, insightProps }: EditorFilterProps): JSX.Element | null {
    const { isFormulaOn } = useValues(trendsLogic(insightProps))
    const { setFilters } = useActions(trendsLogic(insightProps))
    const [value, setValue] = useState(filters.formula)

    useEffect(() => {
        // Don't clear the formula so that the value is still there after toggling the formula switch
        if (filters.formula) {
            setValue(filters.formula)
        }
    }, [filters.formula])

    return isFormulaOn ? (
        <div className="flex items-center gap-2">
            <LemonInput
                className="flex-1"
                placeholder="Example: (A + B) / 100"
                autoFocus
                value={value}
                onChange={(value) => {
                    let changedValue = value.toLocaleUpperCase()
                    // Only allow typing of allowed characters
                    changedValue = changedValue
                        .split('')
                        .filter((d) => ALLOWED_FORMULA_CHARACTERS.test(d))
                        .join('')
                    setValue(changedValue)
                }}
                onBlur={(e) => {
                    // Ignore TrendsFormulaLabel switch click to prevent conflicting setFilters calls
                    // Type assertion is needed because for some React relatedTarget isn't defined as an element
                    // in React types - and it is in reality
                    if (
                        (e.relatedTarget as HTMLElement | undefined)?.id !== 'trends-formula-switch' &&
                        value !== filters.formula
                    ) {
                        setFilters({ formula: value })
                    }
                }}
                onFocus={() => {
                    // When autofocus kicks in, set local value in filters
                    if (value && value !== filters.formula) {
                        setFilters({ formula: value })
                    }
                }}
                onPressEnter={() => {
                    if (value !== filters.formula) {
                        setFilters({ formula: value })
                    }
                }}
            />
        </div>
    ) : null
}

export function TrendsFormulaLabel({ insightProps }: EditorFilterProps): JSX.Element {
    const { setIsFormulaOn } = useActions(trendsLogic(insightProps))
    const { isFormulaOn } = useValues(trendsLogic(insightProps))

    return (
        <>
            <span>Formula</span>
            <LemonSwitch checked={isFormulaOn} onChange={setIsFormulaOn} size="small" id="trends-formula-switch" />
        </>
    )
}
