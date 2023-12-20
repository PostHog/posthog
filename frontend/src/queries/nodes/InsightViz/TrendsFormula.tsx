import { LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { EditorFilterProps } from '~/types'

// When updating this regex, remember to update the regex with the same name in mixins/common.py
const ALLOWED_FORMULA_CHARACTERS = /^[a-zA-Z \-*^0-9+/().]+$/

export function TrendsFormula({ insightProps }: EditorFilterProps): JSX.Element | null {
    const { formula, hasFormula } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const [value, setValue] = useState(formula ? formula : undefined)

    useEffect(() => {
        // Don't clear the formula so that the value is still there after toggling the formula switch
        if (formula) {
            setValue(formula)
        }
    }, [formula])

    return hasFormula ? (
        <div className="flex items-center gap-2">
            <LemonInput
                className="flex-1"
                placeholder="Example: (A + B) / 100"
                autoFocus
                value={value ? value : undefined}
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
                    // Ignore TrendsFormulaLabel switch click to prevent conflicting updateInsightFilter calls
                    // Type assertion is needed because for some React relatedTarget isn't defined as an element
                    // in React types - and it is in reality
                    if (
                        (e.relatedTarget as HTMLElement | undefined)?.id !== 'trends-formula-switch' &&
                        value !== formula
                    ) {
                        updateInsightFilter({ formula: value })
                    }
                }}
                onFocus={() => {
                    // When autofocus kicks in, set local value in filters
                    if (value && value !== formula) {
                        updateInsightFilter({ formula: value })
                    }
                }}
                onPressEnter={() => {
                    if (value !== formula) {
                        updateInsightFilter({ formula: value })
                    }
                }}
            />
        </div>
    ) : null
}
