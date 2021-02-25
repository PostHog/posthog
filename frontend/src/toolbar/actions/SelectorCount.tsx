import React, { useMemo } from 'react'
import { querySelectorAllDeep } from 'query-selector-shadow-dom'

interface SelectorCountProps {
    selector: string
}

export function SelectorCount({ selector }: SelectorCountProps): JSX.Element {
    const [matches, selectorError] = useMemo(() => {
        let hasError = false
        let matchesCount = 0
        if (selector) {
            try {
                matchesCount = querySelectorAllDeep(selector).length
            } catch {
                hasError = true
            }
        }
        return [matchesCount, hasError]
    }, [selector])

    return (
        <small style={{ float: 'right', color: selectorError ? 'red' : '' }}>
            {selectorError ? 'Invalid selector' : `Matches ${matches} element${matches === 1 ? '' : 's'}`}
        </small>
    )
}
