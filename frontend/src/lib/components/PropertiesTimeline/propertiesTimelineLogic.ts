import { Properties } from '@posthog/plugin-scaffold'
import api from 'lib/api'
import { dayjs, Dayjs } from 'lib/dayjs'
import { toParams } from 'lib/utils'
import { ActorType, PropertiesTimelineFilterType } from '~/types'
import { kea, key, props, path, connect, afterMount } from 'kea'
import { loaders } from 'kea-loaders'

import type { propertiesTimelineLogicType } from './propertiesTimelineLogicType'
import { teamLogic } from 'scenes/teamLogic'

export interface PropertiesTimelinePoint {
    timestamp: Dayjs
    properties: Properties
    relevant_event_count: number
}

export interface RawPropertiesTimelinePoint extends Omit<PropertiesTimelinePoint, 'timestamp'> {
    timestamp: string
}

export interface PropertiesTimelineProps {
    actor: ActorType
    filter: PropertiesTimelineFilterType // Might want to support a filter-less timeline for Person pages
}

export const propertiesTimelineLogic = kea<propertiesTimelineLogicType>([
    path(['lib', 'components', 'PropertiesTimeline', 'propertiesTimelineLogic']),
    props({} as PropertiesTimelineProps),
    key((props) => `${props.actor.id}-${JSON.stringify(props.filter)}`),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),
    loaders(({ values, props }) => ({
        points: [
            [] as PropertiesTimelinePoint[],
            {
                loadPoints: async () => {
                    if (props.actor.type === 'person') {
                        const response = await api.get(
                            `api/projects/${values.currentTeamId}/persons/${
                                props.actor.uuid
                            }/properties_timeline/?${toParams(props.filter)}`
                        )
                        return response.map((point: RawPropertiesTimelinePoint) => ({
                            ...point,
                            timestamp: dayjs(point.timestamp),
                        }))
                    }
                    return [] // TODO: Support groups
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadPoints()
    }),
])
