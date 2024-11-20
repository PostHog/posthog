import api from 'lib/api'
import { useEffect, useState } from 'react'

import { HogQLQuery, NodeKind } from '~/queries/schema'
import { hogql } from '~/queries/utils'

interface MetalyticsSummaryProps {
    instance_id: string | null
}

const loadResults = async (instance_id: string) => {
    const query: HogQLQuery = {
        kind: NodeKind.HogQLQuery,
        query: hogql`SELECT count(distinct app_source_id) as count
        FROM app_metrics
        WHERE app_source = 'metalytics'
        AND instance_id = ${instance_id}`,
    }

    const response = await api.query(query)
    const result = response.results as number[]

    return result[0]
}

export function MetalyticsSummary({ instance_id }: MetalyticsSummaryProps): JSX.Element {
    const [results, setResults] = useState<any>()

    useEffect(() => {
        if (!instance_id) {
            return
        }
        loadResults(instance_id)
            .then((results) => {
                setResults(results)
            })
            .catch((error) => {
                console.error('Error loading results', error)
            })
    }, [instance_id])

    if (!instance_id) {
        return <>nope!</>
    }

    return <div className="border p-2 rounded">hi: {results}</div>
}
