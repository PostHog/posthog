import { querySelectorAllDeep } from 'query-selector-shadow-dom'
import { useMemo } from 'react'

interface SelectorCountProps {
    selector: string | null
}

export function SelectorCount({ selector }: SelectorCountProps): JSX.Element | null {
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

    return selector === null ? null : (
        <>
            <small className={`float-right ${selectorError && 'text-danger'}`}>
                {selectorError ? 'Invalid selector' : `Matches ${matches} element${matches === 1 ? '' : 's'}`}
            </small>
        </>
    )
}
