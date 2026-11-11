import { useContext, useEffect, useMemo } from 'react'

import { pluralize } from 'lib/utils/strings'

import { SelectorCountContext } from './SelectorCountContext'

interface SelectorCountProps {
    selector: string | null
}

export function SelectorCount({ selector }: SelectorCountProps): JSX.Element | null {
    const counter = useContext(SelectorCountContext)

    useEffect(() => {
        if (selector) {
            counter.request(selector)
        }
    }, [counter, selector])

    const count = useMemo(() => (selector ? counter.count(selector) : 0), [counter, selector])

    if (selector === null || count === undefined) {
        return null
    }

    return (
        <>
            <small className={`float-right ${count === null && 'text-danger'}`}>
                {count === null ? 'Invalid selector' : `Matches ${pluralize(count, 'element')}`}
            </small>
        </>
    )
}
