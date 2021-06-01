import React, { useMemo } from 'react'
import { querySelectorAllDeep } from 'query-selector-shadow-dom'

interface SelectorCountProps {
    selector: string
}

export function SelectorCount({ selector }: SelectorCountProps): JSX.Element {
    const [matches, selectorError] = useMemo(() => {
        let _selectorError = false
        let _matches = 0
        if (selector) {
            try {
                _matches = querySelectorAllDeep(selector).length
            } catch {
                _selectorError = true
            }
        }
        return [_matches, _selectorError]
    }, [selector])

    return (
        <small style={{ float: 'right', color: selectorError ? 'red' : '' }}>
            {selectorError ? 'Invalid selector' : `Matches ${matches} element${matches === 1 ? '' : 's'}`}
        </small>
    )
}
