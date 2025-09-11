import { useValues } from 'kea'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { networkViewLogic } from 'scenes/session-recordings/apm/networkViewLogic'
import { initiatorTypeToColor } from 'scenes/session-recordings/apm/performance-event-utils'
import { TimeLineView } from 'scenes/session-recordings/apm/waterfall/TimeLineView'

import { PerformanceEvent } from '~/types'

/**
 * When displaying a waterfall view
 * we can show the time that a particular entry took
 * in the context of the entire page.
 */
export function NetworkBar({ item }: { item: PerformanceEvent }): JSX.Element | null {
    const { positionPercentagesFor } = useValues(networkViewLogic)

    const positionPercentages = positionPercentagesFor(item)

    return (
        <Tooltip delayMs={0} title={<TimeLineView performanceEvent={item} />}>
            <div
                className="relative h-5 cursor-pointer"
                /* eslint-disable-next-line react/forbid-dom-props */
                style={{
                    backgroundColor: initiatorTypeToColor(item.initiator_type || 'other'),
                    width: positionPercentages?.widthPercentage ?? '0%',
                    left: positionPercentages?.startPercentage ?? '0%',
                }}
            />
        </Tooltip>
    )
}
