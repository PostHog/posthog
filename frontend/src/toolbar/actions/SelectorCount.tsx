import React, { useMemo } from 'react'
import { querySelectorAllDeep } from 'query-selector-shadow-dom'

interface SelectorCountProps {
    selector: string
}

export function SelectorCount({ selector }: SelectorCountProps): JSX.Element {
    const [matches, selectorError] = useMemo(() => {
        let selectorError = false
        let matches = 0
        if (selector) {
            try {
                matches = querySelectorAllDeep(selector).length
            } catch {
                selectorError = true
            }
        }
        return [matches, selectorError]
    }, [selector])

    return (
        <small style={{ float: 'right', color: selectorError ? 'red' : '' }}>
            {selectorError ? 'Invalid selector' : `Matches ${matches} element${matches === 1 ? '' : 's'}`}
        </small>
    )
}
