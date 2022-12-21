import { Properties } from '@posthog/plugin-scaffold'
import api from 'lib/api'
import { Dayjs } from 'lib/dayjs'
import { toParams } from 'lib/utils'
import { useEffect, useState } from 'react'
import { ActorType, PropertiesTimelineFilterType } from '~/types'
import { PropertiesTable } from './PropertiesTable'

export interface PropertiesTimelinePoint {
    timestamp: Dayjs
    properties: Properties
    relevant_event_count: number
}

export interface PropertiesTimelineProps {
    actor: ActorType
    filter: PropertiesTimelineFilterType
}

function useTimeline(actor: ActorType, filter: PropertiesTimelineFilterType): PropertiesTimelinePoint[] | null {
    const [timeline, setTimeline] = useState<PropertiesTimelinePoint[] | null>(null)

    useEffect(() => {
        if (actor.type === 'person') {
            api.get(`api/person/${actor.id}/properties_timeline/?${toParams(filter)}`).then((response) => {
                setTimeline(response.results)
            })
        }
    }, [actor.id])

    return timeline
}

export function PropertiesTimeline({ actor, filter }: PropertiesTimelineProps): JSX.Element {
    const timeline = useTimeline(actor, filter)

    return timeline ? (
        <>
            {timeline.map((point) => (
                <div key={point.timestamp.toISOString()}>
                    <h3 className="text-center">{point.timestamp.format('MMMM Do YYYY, h:mm:ss a')}</h3>
                    <PropertiesTable properties={point.properties} nestingLevel={1} className="px-2" />
                </div>
            ))}
        </>
    ) : (
        <>
            {Object.keys(actor.properties).length ? (
                <PropertiesTable properties={actor.properties} nestingLevel={1} className="px-2" />
            ) : (
                <p className="text-center m-4">There are no properties.</p>
            )}
        </>
    )
}
