import equal from 'fast-deep-equal'
import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { parsePersonFromHogQLRow } from 'scenes/persons/person-utils'
import { teamLogic } from 'scenes/teamLogic'
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

export const aggregateRecordingCountsByPerson = (
    persons: PersonType[],
    countsByDistinctId: Record<string, number>
): Record<string, number> => {
    const byKey: Record<string, number> = {}
    for (const person of persons) {
        const key = person.id ?? person.uuid
        if (!key) {
            continue
        }
        let total = 0
        for (const distinctId of person.distinct_ids ?? []) {
            total += countsByDistinctId[distinctId] ?? 0
        }
        if (total > 0) {
            byKey[key] = total
        }
    }
    return byKey
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
            teamLogic,
            ['currentTeam'],
        ],
    })),
    actions({
        refresh: true,
    }),
    loaders(({ values }) => ({
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
        recordingCountsByDistinctId: [
            {} as Record<string, number>,
            {
                loadRecordingCounts: async ({ distinctIds }: { distinctIds: string[] }) => {
                    if (!values.currentTeam?.session_recording_opt_in) {
                        return {}
                    }
                    const { identified } = partitionDistinctIds(distinctIds)
                    if (identified.length === 0) {
                        return {}
                    }
                    const limitedIds = identified.slice(0, PERSON_HYDRATION_LIMIT)
                    const query = hogql`SELECT
                            distinct_id,
                            count(DISTINCT session_id) AS recording_count
                        FROM session_replay_events
                        WHERE distinct_id IN ${limitedIds}
                            AND min_first_timestamp >= now() - INTERVAL 30 MINUTE
                        GROUP BY distinct_id`

                    const response = (await performQuery({
                        kind: NodeKind.HogQLQuery,
                        query,
                        tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                    })) as HogQLQueryResponse
                    const rows = (response.results ?? []) as [string, number | string][]
                    const counts: Record<string, number> = {}
                    for (const [distinctId, recordingCount] of rows) {
                        const n = Number(recordingCount)
                        if (distinctId && Number.isFinite(n) && n > 0) {
                            counts[distinctId] = n
                        }
                    }
                    return counts
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
        recordingCountByPersonKey: [
            (s) => [s.persons, s.recordingCountsByDistinctId],
            (persons: PersonType[], counts: Record<string, number>): Record<string, number> =>
                aggregateRecordingCountsByPerson(persons, counts),
            { resultEqualityCheck: equal },
        ],
    }),
    listeners(({ actions, values }) => ({
        refresh: () => {
            actions.loadPersons({ distinctIds: values.identifiedDistinctIds })
            if (values.currentTeam?.session_recording_opt_in) {
                actions.loadRecordingCounts({ distinctIds: values.identifiedDistinctIds })
            }
        },
    })),
    events(({ actions, values }) => ({
        afterMount: () => {
            actions.loadPersons({ distinctIds: values.identifiedDistinctIds })
            if (values.currentTeam?.session_recording_opt_in) {
                actions.loadRecordingCounts({ distinctIds: values.identifiedDistinctIds })
            }
        },
    })),
])
