import { TrendsQuery } from '~/queries/schema'

export function TrendsQuery({ query }: { query: TrendsQuery }): JSX.Element {
    return (
        <span>
            TrendsQuery: <pre>{JSON.stringify(query, null, 2)}</pre>
        </span>
    )
}
