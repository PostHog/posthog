import { AnyResponseType, CoreWebVitalsQuery } from '~/queries/schema'
import { QueryContext } from '~/queries/types'

export function CoreWebVitals(props: {
    query: CoreWebVitalsQuery
    cachedResults?: AnyResponseType
    context: QueryContext
}): JSX.Element | null {
    return <span>{props.query.kind}</span>
}
