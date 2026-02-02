import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { isUUIDLike } from 'lib/utils'
import { personsSceneLogic } from 'scenes/persons/personsSceneLogic'
import { urls } from 'scenes/urls'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { ActorsQueryResponse } from '~/queries/schema/schema-general'

interface PersonDisplayNameNudgeBannerProps {
    uniqueKey: string
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

export function PersonDisplayNameNudgeBanner({ uniqueKey }: PersonDisplayNameNudgeBannerProps): JSX.Element | null {
    const { query, showDisplayNameNudge, isBannerLoading } = useValues(personsSceneLogic)
    const { setShowDisplayNameNudge, setIsBannerLoading } = useActions(personsSceneLogic)

    const dataKey = `DataNode.${uniqueKey}`
    const vizKey = insightVizDataNodeKey({
        dashboardItemId: `new-AdHoc.${dataKey}`,
        dataNodeCollectionId: dataKey,
    })

    const { response, dataLoading, isRefresh } = useValues(
        dataNodeLogic({
            key: vizKey,
            query: query.source,
        })
    )

    useEffect(() => {
        setIsBannerLoading(dataLoading && !isRefresh)
        const persons = getPersonsFromResponse(response as ActorsQueryResponse | null)
        if (!persons.length) {
            return
        }
        const uuidCount = persons.filter((person) => {
            return isUUIDLike(person.display_name)
        }).length
        const shouldShow = dataLoading || uuidCount / persons.length > UUID_THRESHOLD
        setShowDisplayNameNudge(shouldShow)
    }, [response, dataLoading, isRefresh])

    if (isBannerLoading) {
        return <LemonSkeleton className="h-14 my-2" />
    }

    if (!showDisplayNameNudge) {
        return null
    }

    return (
        <LemonBanner
            type="info"
            className="my-2"
            dismissKey="person-display-name-uuid-nudge"
            action={{
                children: 'Configure',
                to: urls.settings('environment-product-analytics', 'person-display-name'),
                'data-attr': 'person-display-name-uuid-nudge-action',
            }}
        >
            Your persons are showing IDs instead of names. Configure display name properties to show meaningful names
            like email or username.
        </LemonBanner>
    )
}
