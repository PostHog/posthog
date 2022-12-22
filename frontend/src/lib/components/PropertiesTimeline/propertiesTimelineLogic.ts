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

export interface RawPropertiesTimelinePoint extends Omit<PropertiesTimelinePoint, 'timestamp'> {
    timestamp: string
}

export interface RawPropertiesTimelineResult {
    points: RawPropertiesTimelinePoint[]
    crucial_property_keys: string[]
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
        // This reducer is for loading convenience, for actual data use `points` and `crucialPropertyKeys`
        result: [
            {
                points: [],
                crucial_property_keys: [],
            } as RawPropertiesTimelineResult,
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
                    return {
                        points: [],
                        crucial_property_keys: [],
                    }
                },
            },
        ],
    })),
    selectors({
        points: [
            (s) => [s.result, s.timezone],
            (result, timezone) =>
                result.points.map((point) => ({
                    ...point,
                    timestamp: dayjsUtcToTimezone(point.timestamp, timezone),
                })),
        ],
        crucialPropertyKeys: [(s) => [s.result], (result) => result.crucial_property_keys],
    }),
    afterMount(({ actions }) => {
        actions.loadResult()
    }),
])
