import { useState } from 'react'

import { SimpleKeyValueList } from 'lib/components/SimpleKeyValueList'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { TimeLineView, convertForTimelineView } from 'scenes/session-recordings/apm/waterfall/TimeLineView'

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

    const { isValid: isValidForTimelineView } = convertForTimelineView(performanceEvent)

    return (
        <div className="flex flex-col deprecated-space-y-2">
            <div className="flex flex-row justify-end">
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    onClick={() => setTimelineMode(!timelineMode)}
                    data-attr={`switch-timing-to-${timelineMode ? 'table' : 'timeline'}-view`}
                    disabledReason={
                        isValidForTimelineView ? undefined : 'No performance data available for timeline view.'
                    }
                >
                    {timelineMode && isValidForTimelineView ? 'Table view' : 'Timeline view'}
                </LemonButton>
            </div>
            <LemonDivider dashed={true} />
            {timelineMode && isValidForTimelineView ? (
                <TimeLineView performanceEvent={performanceEvent} />
            ) : (
                <TableView performanceEvent={performanceEvent} />
            )}
        </div>
    )
}
