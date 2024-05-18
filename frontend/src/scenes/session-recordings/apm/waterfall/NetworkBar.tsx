import { useValues } from 'kea'
import { getSeriesColor } from 'lib/colors'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { networkViewLogic } from 'scenes/session-recordings/apm/networkViewLogic'
import { TimeLineView } from 'scenes/session-recordings/apm/waterfall/TimeLineView'

import { PerformanceEvent } from '~/types'

const initiatorTypeToColor = {
    navigation: getSeriesColor(13),
    css: getSeriesColor(14),
    script: getSeriesColor(15),
    xmlhttprequest: getSeriesColor(16),
    fetch: getSeriesColor(17),
    beacon: getSeriesColor(18),
    video: getSeriesColor(19),
    audio: getSeriesColor(20),
    track: getSeriesColor(21),
    img: getSeriesColor(22),
    image: getSeriesColor(23),
    input: getSeriesColor(24),
    a: getSeriesColor(25),
    iframe: getSeriesColor(26),
    frame: getSeriesColor(27),
    other: getSeriesColor(28),
}

/**
 * When displaying a waterfall view
 * we can show the time that a particular entry took
 * in the context of the entire page.
 */
export function NetworkBar({ item }: { item: PerformanceEvent }): JSX.Element | null {
    const { positionPercentagesFor } = useValues(networkViewLogic)

    const positionPercentages = positionPercentagesFor(item)

    return (
        <Tooltip title={<TimeLineView performanceEvent={item} />}>
            <div
                className="relative h-full"
                /* eslint-disable-next-line react/forbid-dom-props */
                style={{
                    backgroundColor: initiatorTypeToColor[item.initiator_type || 'other'] ?? 'red',
                    width: positionPercentages?.widthPercentage ?? '0%',
                    left: positionPercentages?.startPercentage ?? '0%',
                }}
            />
        </Tooltip>
    )
}
