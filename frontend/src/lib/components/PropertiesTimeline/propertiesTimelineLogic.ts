import { Properties } from '@posthog/plugin-scaffold'
import api from 'lib/api'
import { Dayjs, dayjsUtcToTimezone } from 'lib/dayjs'
import { toParams } from 'lib/utils'
import { ActorType, PropertiesTimelineFilterType } from '~/types'
import { kea, key, props, path, connect, afterMount, selectors, reducers, actions } from 'kea'
import { loaders } from 'kea-loaders'

import type { propertiesTimelineLogicType } from './propertiesTimelineLogicType'
import { teamLogic } from 'scenes/teamLogic'

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
    connect({
        values: [teamLogic, ['currentTeamId', 'timezone']],
    }),
    actions({
        setSelectedPointIndex: (index: number | null) => ({ index }),
    }),
    reducers({
        selectedPointIndex: [
            null as number | null,
            {
                setSelectedPointIndex: (_, { index }) => index,
                loadResultSuccess: (_, { result }) => result.points.length - 1,
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
                        const response = (await api.get(
                            `api/projects/${values.currentTeamId}/persons/${
                                props.actor.uuid
                            }/properties_timeline/?${toParams(props.filter)}`
                        )) as RawPropertiesTimelineResult
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
