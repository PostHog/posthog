import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { useState } from 'react'
import { TimeLineView } from 'scenes/session-recordings/apm/waterfall/TimeLineView'
import { SimpleKeyValueList } from 'scenes/session-recordings/player/inspector/components/SimpleKeyValueList'

import { PerformanceEvent } from '~/types'

const TableView = ({ performanceEvent }: { performanceEvent: PerformanceEvent }): JSX.Element => {
    const timingProperties = Object.entries(performanceEvent).reduce((acc, [key, val]) => {
        if (key.includes('time') || key.includes('end') || key.includes('start')) {
            acc[key] = val
        }
        return acc
    }, {})
    return <SimpleKeyValueList item={timingProperties} />
}

export const NetworkRequestTiming = ({
    performanceEvent,
}: {
    performanceEvent: PerformanceEvent
}): JSX.Element | null => {
    const [timelineMode, setTimelineMode] = useState<boolean>(true)

    // if timeline view renders null then we fall back to table view
    const timelineView = timelineMode ? <TimeLineView performanceEvent={performanceEvent} /> : null

    return (
        <div className="flex flex-col space-y-2">
            <div className="flex flex-row justify-end">
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    onClick={() => setTimelineMode(!timelineMode)}
                    data-attr={`switch-timing-to-${timelineMode ? 'table' : 'timeline'}-view`}
                >
                    {timelineMode ? 'Table view' : 'Timeline view'}
                </LemonButton>
            </div>
            <LemonDivider dashed={true} />
            {timelineMode && timelineView ? timelineView : <TableView performanceEvent={performanceEvent} />}
        </div>
    )
}
