import { useValues } from 'kea'

import { resultsBreakdownLogic } from './resultsBreakdownLogic'
import type { ResultBreakdownRenderProps } from './types'

export const ResultsBreakdownContent = ({
    children,
}: {
    children?: (props: ResultBreakdownRenderProps) => JSX.Element | null
}): JSX.Element | null => {
    const { query, breakdownResults } = useValues(resultsBreakdownLogic)

    /**
     * if `children` is a function, we call it with the query and breakdown results,
     * otherwise we return null.
     * children can narrow the props type to omit or make it non-nullable.
     */
    return children && typeof children === 'function' ? children({ query, breakdownResults }) : null
}
