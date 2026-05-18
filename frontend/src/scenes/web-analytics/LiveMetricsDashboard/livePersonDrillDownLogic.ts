import equal from 'fast-deep-equal'
import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { parsePersonFromHogQLRow } from 'scenes/persons/person-utils'
import { WEB_ANALYTICS_DEFAULT_QUERY_TAGS } from 'scenes/web-analytics/common'

import { performQuery } from '~/queries/query'
import { HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { PersonType } from '~/types'

import { LiveMetricsSlidingWindow } from './LiveMetricsSlidingWindow'
import { LivePersonDrillDownBreakdownType, livePersonDrillDownDrawerLogic } from './livePersonDrillDownDrawerLogic'
import type { livePersonDrillDownLogicType } from './livePersonDrillDownLogicType'
import { liveWebAnalyticsMetricsLogic } from './liveWebAnalyticsMetricsLogic'

export const COOKIELESS_DISTINCT_ID_PREFIX = 'cookieless_'
export const PERSON_HYDRATION_LIMIT = 200

export interface LivePersonDrillDownLogicProps {
    breakdownType: LivePersonDrillDownBreakdownType
    breakdownValue: string
}

export const partitionDistinctIds = (distinctIds: string[]): { identified: string[]; anonymous: string[] } => {
    const identified: string[] = []
    const anonymous: string[] = []
    for (const id of distinctIds) {
        if (id.startsWith(COOKIELESS_DISTINCT_ID_PREFIX)) {
            anonymous.push(id)
        } else {
            identified.push(id)
        }
    }
    return { identified, anonymous }
}

export const livePersonDrillDownLogic = kea<livePersonDrillDownLogicType>([
    props({} as LivePersonDrillDownLogicProps),
    key((p) => `${p.breakdownType}:${p.breakdownValue}`),
    path((logicKey) => ['scenes', 'webAnalytics', 'livePersonDrillDownLogic', logicKey]),
    connect(() => ({
        values: [
            liveWebAnalyticsMetricsLogic,
            ['slidingWindow', 'eventsVersion', 'geoVersion'],
            livePersonDrillDownDrawerLogic,
            ['currentSelection'],
        ],
    })),
    actions({
        refresh: true,
    }),
    loaders(() => ({
        persons: [
            [] as PersonType[],
            {
                loadPersons: async ({ distinctIds }: { distinctIds: string[] }) => {
                    const { identified } = partitionDistinctIds(distinctIds)
                    if (identified.length === 0) {
                        return []
                    }
                    const limitedIds = identified.slice(0, PERSON_HYDRATION_LIMIT)
                    const query = hogql`SELECT
                            id,
                            groupArray(101)(pdi2.distinct_id) AS distinct_ids,
                            properties,
                            is_identified,
                            created_at,
                            last_seen_at
                        FROM persons
                        LEFT JOIN (
                            SELECT
                                pdi2.distinct_id,
                                argMax(pdi2.person_id, pdi2.version) AS person_id
                            FROM raw_person_distinct_ids pdi2
                            WHERE pdi2.distinct_id IN (
                                SELECT distinct_id
                                FROM raw_person_distinct_ids
                                WHERE person_id IN (
                                    SELECT argMax(person_id, version) AS person_id
                                    FROM raw_person_distinct_ids
                                    WHERE distinct_id IN ${limitedIds}
                                    GROUP BY distinct_id
                                    HAVING argMax(is_deleted, version) = 0
                                )
                            )
                            GROUP BY pdi2.distinct_id
                            HAVING argMax(pdi2.is_deleted, pdi2.version) = 0
                        ) AS pdi2 ON pdi2.person_id = persons.id
                        WHERE persons.id IN (
                            SELECT argMax(person_id, version) AS person_id
                            FROM raw_person_distinct_ids
                            WHERE distinct_id IN ${limitedIds}
                            GROUP BY distinct_id
                            HAVING argMax(is_deleted, version) = 0
                        )
                        GROUP BY id, properties, is_identified, created_at, last_seen_at
                        ORDER BY last_seen_at DESC
                        LIMIT ${PERSON_HYDRATION_LIMIT}`

                    const response = (await performQuery({
                        kind: NodeKind.HogQLQuery,
                        query,
                        tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                    })) as HogQLQueryResponse
                    return (response.results ?? []).map(parsePersonFromHogQLRow)
                },
            },
        ],
    })),
    reducers({
        displayedDistinctIds: [
            [] as string[],
            {
                loadPersons: (_, { distinctIds }) => distinctIds,
            },
        ],
    }),
    selectors({
        currentDistinctIds: [
            (s) => [s.slidingWindow, s.eventsVersion, s.geoVersion, (_, p) => p],
            (
                slidingWindow: LiveMetricsSlidingWindow,
                _eventsVersion: number,
                _geoVersion: number,
                props: LivePersonDrillDownLogicProps
            ): string[] => slidingWindow.getDistinctIdsFor(props.breakdownType, props.breakdownValue),
            { resultEqualityCheck: equal },
        ],
        partitionedDistinctIds: [
            (s) => [s.currentDistinctIds],
            (distinctIds: string[]): { identified: string[]; anonymous: string[] } => partitionDistinctIds(distinctIds),
            { resultEqualityCheck: equal },
        ],
        identifiedDistinctIds: [
            (s) => [s.partitionedDistinctIds],
            (partitioned: { identified: string[] }): string[] => partitioned.identified,
        ],
        anonymousCount: [
            (s) => [s.partitionedDistinctIds],
            (partitioned: { anonymous: string[] }): number => partitioned.anonymous.length,
        ],
        totalCount: [(s) => [s.currentDistinctIds], (distinctIds: string[]): number => distinctIds.length],
        identifiedCount: [(s) => [s.identifiedDistinctIds], (identified: string[]): number => identified.length],
        newVisitorCount: [
            (s) => [s.identifiedDistinctIds, s.displayedDistinctIds],
            (current: string[], displayed: string[]): number => {
                if (displayed.length === 0) {
                    return 0
                }
                const displayedSet = new Set(displayed)
                let n = 0
                for (const id of current) {
                    if (!displayedSet.has(id)) {
                        n++
                    }
                }
                return n
            },
        ],
        isTruncated: [
            (s) => [s.identifiedCount],
            (identifiedCount: number): boolean => identifiedCount > PERSON_HYDRATION_LIMIT,
        ],
    }),
    listeners(({ actions, values }) => ({
        refresh: () => {
            actions.loadPersons({ distinctIds: values.identifiedDistinctIds })
        },
    })),
    events(({ actions, values }) => ({
        afterMount: () => {
            actions.loadPersons({ distinctIds: values.identifiedDistinctIds })
        },
    })),
])
