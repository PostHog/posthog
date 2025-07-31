import { actions, afterMount, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { Properties } from '@posthog/plugin-scaffold'

import { Dayjs, dayjsUtcToTimezone } from 'lib/dayjs'
import { apiGetWithTimeToSeeDataTracking } from 'lib/internalMetrics'
import { toParams, uuid } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import { ActorType, PropertiesTimelineFilterType } from '~/types'

import type { propertiesTimelineLogicType } from './propertiesTimelineLogicType'

export interface PropertiesTimelinePoint {
    timestamp: Dayjs
    properties: Properties
    relevantEventCount: number
}

export interface RawPropertiesTimelinePoint {
    timestamp: string
    properties: Properties
    relevant_event_count: number
}

export interface RawPropertiesTimelineResult {
    points: RawPropertiesTimelinePoint[]
    crucial_property_keys: string[]
    effective_date_from: string
    effective_date_to: string
}

export interface PropertiesTimelineProps {
    actor: ActorType
    filter: PropertiesTimelineFilterType
}

export const propertiesTimelineLogic = kea<propertiesTimelineLogicType>([
    path(['lib', 'components', 'PropertiesTimeline', 'propertiesTimelineLogic']),
    props({} as PropertiesTimelineProps),
    key((props) => `${props.actor.id}-${JSON.stringify(props.filter)}`),
    connect(() => ({
        values: [teamLogic, ['currentTeamId', 'timezone']],
    })),
    actions({
        setSelectedPointIndex: (index: number | null) => ({ index }),
    }),
    reducers({
        selectedPointIndex: [
            null as number | null,
            {
                setSelectedPointIndex: (_, { index }) => index,
                loadResultSuccess: (_, { result }) =>
                    result.crucial_property_keys.length > 0 && result.points.length > 0
                        ? result.points.length - 1
                        : null,
            },
        ],
    }),
    loaders(({ values, props }) => ({
        // This reducer is for loading convenience, for actual data use `points`, `crucialPropertyKeys`, and `dateRange`
        result: [
            null as RawPropertiesTimelineResult | null,
            {
                loadResult: async () => {
                    if (props.actor.type === 'person') {
                        const queryId = uuid()
                        const response = await apiGetWithTimeToSeeDataTracking<RawPropertiesTimelineResult>(
                            `api/environments/${values.currentTeamId}/persons/${
                                props.actor.id
                            }/properties_timeline/?${toParams(props.filter)}`,
                            values.currentTeamId,
                            {
                                type: 'properties_timeline_load',
                                context: 'actors_modal',
                                primary_interaction_id: queryId,
                                query_id: queryId,
                                insights_fetched: 1,
                                insights_fetched_cached: 0, // TODO: Cache properties timeline requests eventually
                                is_primary_interaction: true,
                            }
                        )
                        if (response.points.length === 0) {
                            // It should not be possible for a properties timeline to have zero points, as all actors
                            // shown in the actors modal must have at least one relevant event in the period
                            posthog.captureException(new Error('Properties Timeline returned no points'), {
                                tags: { 'team.id': values.currentTeamId },
                                extra: {
                                    params: props.filter,
                                },
                            })
                        }
                        return response
                    }
                    throw new Error("Properties Timeline doesn't support groups-on-events yet")
                },
            },
        ],
    })),
    selectors({
        points: [
            (s) => [s.result, s.timezone],
            (result, timezone) =>
                result
                    ? result.points.map(
                          (point): PropertiesTimelinePoint => ({
                              relevantEventCount: point.relevant_event_count,
                              properties: point.properties,
                              timestamp: dayjsUtcToTimezone(point.timestamp, timezone),
                          })
                      )
                    : [],
        ],
        crucialPropertyKeys: [
            (s) => [s.result],
            (result): (keyof Properties)[] => (result ? result.crucial_property_keys : []),
        ],
        dateRange: [
            (s) => [s.result, s.timezone],
            (result, timezone): [Dayjs, Dayjs] | null =>
                result && [
                    dayjsUtcToTimezone(result.effective_date_from, timezone),
                    dayjsUtcToTimezone(result.effective_date_to, timezone),
                ],
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadResult()
    }),
])
