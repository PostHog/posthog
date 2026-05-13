import { BuiltLogic, LogicWrapper, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { Query } from '~/queries/Query/Query'
import { DataTableNode, EventsQuery, EventsQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import { PERSON_EVENTS_CONTEXT_KEY } from './personsLogic'

const DEFAULT_AFTER = '-24h'
const EXPANDED_AFTER = '-7d'

interface PersonEventsTabProps {
    eventsQuery: DataTableNode | null
    setEventsQuery: (query: DataTableNode | null) => void
    eventsQueryLogicKey: string
    tabId?: string
    attachTo: BuiltLogic | LogicWrapper
}

export function PersonEventsTab({
    eventsQuery,
    setEventsQuery,
    eventsQueryLogicKey,
    tabId,
    attachTo,
}: PersonEventsTabProps): JSX.Element | null {
    const insightProps: InsightLogicProps = {
        dashboardItemId: `new-${PERSON_EVENTS_CONTEXT_KEY}`,
        tabId,
        dataNodeCollectionId: eventsQueryLogicKey,
    }
    const dataNodeKey = insightVizDataNodeKey(insightProps)

    const source = eventsQuery?.source as EventsQuery | undefined
    const isEventsQuerySource = source?.kind === NodeKind.EventsQuery
    const sourceAfter = isEventsQuerySource ? source?.after : undefined
    const personId = isEventsQuerySource ? source?.personId : undefined

    const { response, responseLoading } = useValues(
        dataNodeLogic({
            key: dataNodeKey,
            query: source,
            dataNodeCollectionId: eventsQueryLogicKey,
        })
    )

    // Auto-expand once per person — if the user manually reverts to 24h, we leave it alone.
    const autoExpandedPersonIdRef = useRef<string | undefined>(undefined)

    useEffect(() => {
        if (!eventsQuery || !isEventsQuerySource || sourceAfter !== DEFAULT_AFTER) {
            return
        }
        if (responseLoading || !personId) {
            return
        }
        if (autoExpandedPersonIdRef.current === personId) {
            return
        }
        const eventsResponse = response as EventsQueryResponse | null
        if (!eventsResponse || !Array.isArray(eventsResponse.results)) {
            return
        }
        if (eventsResponse.results.length > 0) {
            return
        }

        autoExpandedPersonIdRef.current = personId
        setEventsQuery({
            ...eventsQuery,
            source: { ...(source as EventsQuery), after: EXPANDED_AFTER },
        })
        lemonToast.info('No events in the last 24 hours — showing the last 7 days')
    }, [isEventsQuerySource, sourceAfter, responseLoading, response, personId, eventsQuery, source, setEventsQuery])

    if (!eventsQuery) {
        return null
    }

    return (
        <Query
            uniqueKey="person-profile-events"
            attachTo={attachTo}
            query={eventsQuery}
            setQuery={(q) => setEventsQuery(q)}
            context={{
                insightProps: {
                    dashboardItemId: `new-${PERSON_EVENTS_CONTEXT_KEY}`,
                    tabId,
                    dataNodeCollectionId: eventsQueryLogicKey,
                },
            }}
        />
    )
}
