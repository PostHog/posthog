import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { isUUIDLike } from 'lib/utils'
import { urls } from 'scenes/urls'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { ActorsQueryResponse, DataTableNode } from '~/queries/schema/schema-general'

interface PersonDisplayNameNudgeBannerProps {
    query: DataTableNode
    uniqueKey: string
    onShouldShow?: (shouldShow: boolean) => void
}

const UUID_THRESHOLD = 0.5

function getPersonsFromResponse(response: ActorsQueryResponse | null): Record<string, string>[] {
    if (!response?.results) {
        return []
    }
    return response.results.map((result) => {
        const person = result[0]
        if (typeof person === 'object' && person !== null && 'display_name' in person) {
            return person
        }
        return null
    })
}

export function PersonDisplayNameNudgeBanner({
    query,
    uniqueKey,
    onShouldShow,
}: PersonDisplayNameNudgeBannerProps): JSX.Element | null {
    const dataKey = `DataNode.${uniqueKey}`
    const vizKey = insightVizDataNodeKey({
        dashboardItemId: `new-AdHoc.${dataKey}`,
        dataNodeCollectionId: dataKey,
    })

    const { response } = useValues(
        dataNodeLogic({
            key: vizKey,
            query: query.source,
        })
    )

    const shouldShowNudge = useMemo(() => {
        const persons = getPersonsFromResponse(response as ActorsQueryResponse | null)
        if (!persons.length) {
            return false
        }

        const uuidCount = persons.filter((person) => {
            return isUUIDLike(person.display_name)
        }).length

        const shouldShow = uuidCount / persons.length > UUID_THRESHOLD
        onShouldShow?.(shouldShow)
        return shouldShow
    }, [response, onShouldShow])

    if (!shouldShowNudge) {
        return null
    }

    return (
        <LemonBanner
            type="info"
            className="mb-2 mt-2"
            dismissKey="person-display-name-uuid-nudge"
            action={{
                children: 'Configure',
                to: urls.settings('environment-product-analytics', 'person-display-name'),
            }}
        >
            Your persons are showing IDs instead of names. Configure display name properties to show meaningful names
            like email or username.
        </LemonBanner>
    )
}
