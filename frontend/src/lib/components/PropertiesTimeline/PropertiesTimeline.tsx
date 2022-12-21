import { Properties } from '@posthog/plugin-scaffold'
import { dayjs } from 'lib/dayjs'
import { useEffect, useState } from 'react'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { useValues } from 'kea'
import { LemonDivider } from '@posthog/lemon-ui'
import { propertiesTimelineLogic, PropertiesTimelineProps } from './propertiesTimelineLogic'
import { TimelineSeekbar } from '../TimelineSeekbar'

export function PropertiesTimeline({ actor, filter }: PropertiesTimelineProps): JSX.Element {
    const { points, pointsLoading } = useValues(propertiesTimelineLogic({ actor, filter }))
    const [selectedPointIndex, setSelectedPointIndex] = useState<number | null>(null)

    useEffect(() => {
        if (points.length > 0 && selectedPointIndex === null) {
            setSelectedPointIndex(points.length - 1)
        }
    }, [points, selectedPointIndex, setSelectedPointIndex])

    const propertiesShown: Properties =
        points.length > 0 && selectedPointIndex !== null ? points[selectedPointIndex].properties : actor.properties

    return (
        <div className="flex flex-col px-2">
            <TimelineSeekbar
                points={
                    points
                        ? points.map(({ timestamp, relevant_event_count }) => ({
                              timestamp,
                              count: relevant_event_count,
                          }))
                        : []
                }
                selectedPointIndex={selectedPointIndex}
                onPointSelection={setSelectedPointIndex}
                from={filter.date_from ? dayjs(filter.date_from) : undefined}
                to={filter.date_to ? dayjs(filter.date_to) : undefined}
                loading={pointsLoading}
            />
            <LemonDivider className="h-0" />
            {/* TODO: Highlight relevant properties */}
            <PropertiesTable properties={propertiesShown} nestingLevel={1} />
        </div>
    )
}
