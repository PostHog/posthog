import { Query } from '~/queries/Query/Query'
import { useEffect, useState } from 'react'
import { QueryEditor } from '~/queries/QueryEditor/QueryEditor'
import { Node } from '~/queries/schema'

export interface QueryRunnerProps {
    /** The query to render */
    query: Node | string
}

export function QueryRunner(props: QueryRunnerProps): JSX.Element {
    const [queryString, setQueryString] = useState(
        typeof props.query === 'string' ? props.query : JSON.stringify(props.query)
    )
    useEffect(() => {
        const newQueryString = typeof props.query === 'string' ? props.query : JSON.stringify(props.query)
        if (newQueryString !== queryString) {
            setQueryString(newQueryString)
        }
    }, [queryString])

    return (
        <>
            <QueryEditor query={queryString} setQuery={setQueryString} />
            <div className="p-4">
                <Query key={queryString} query={queryString} />
            </div>
        </>
    )
}
