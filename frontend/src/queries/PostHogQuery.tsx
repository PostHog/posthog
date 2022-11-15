import { isLegacyQuery, Node } from './nodes'

export interface PostHogQueryProps {
    query: Node
}
export function PostHogQuery({ query }: PostHogQueryProps): JSX.Element {
    if (isLegacyQuery(query)) {
        return <div>{query.filters.insight}</div>
    }

    return <div />
}
