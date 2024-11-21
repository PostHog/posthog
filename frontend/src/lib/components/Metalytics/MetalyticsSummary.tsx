import { useValues } from 'kea'
import api from 'lib/api'
import { useEffect, useState } from 'react'

import { activityForSceneLogic } from '~/layout/navigation-3000/sidepanel/panels/activity/activityForSceneLogic'
import { HogQLQuery, NodeKind } from '~/queries/schema'
import { hogql } from '~/queries/utils'

const loadResults = async (instance_id: string): Promise<number> => {
    const query: HogQLQuery = {
        kind: NodeKind.HogQLQuery,
        query: hogql`SELECT sum(count) as count
        FROM app_metrics
        WHERE app_source = 'metalytics'
        AND instance_id = ${instance_id}`,
    }

    const response = await api.query(query)
    const result = response.results as number[]

    return result[0]
}

export function MetalyticsSummary(): JSX.Element | null {
    const [results, setResults] = useState<any>()

    const { sceneActivityFilters } = useValues(activityForSceneLogic)

    // null
    // { scope: 'projects', item_id: '12345678' }
    // { scope: 'projects' }

    const instanceId = sceneActivityFilters
        ? sceneActivityFilters.item_id
            ? `${sceneActivityFilters.scope}:${sceneActivityFilters.item_id}`
            : sceneActivityFilters.scope
        : null

    useEffect(() => {
        if (!instanceId) {
            return
        }
        loadResults(instanceId)
            .then((results) => {
                setResults(results)
            })
            .catch((error) => {
                console.error('Error loading results', error)
            })
    }, [instanceId])

    if (!instanceId) {
        return null
    }

    return <div className="border p-2 rounded">hi: {results}</div>
}
