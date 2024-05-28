import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import {
    calculatePerformanceParts,
    perfDescriptions,
    perfSections,
    TimingBar,
} from 'scenes/session-recordings/apm/waterfall/TimingBar'

import { PerformanceEvent } from '~/types'

/**
 * When displaying a waterfall view
 * we can show the parts that make up a performance entry
 */
export const TimeLineView = ({ performanceEvent }: { performanceEvent: PerformanceEvent }): JSX.Element | null => {
    const rangeStart = performanceEvent.start_time
    const rangeEnd = performanceEvent.load_event_end ? performanceEvent.load_event_end : performanceEvent.response_end
    if (typeof rangeStart === 'number' && typeof rangeEnd === 'number') {
        const performanceMeasures = calculatePerformanceParts(performanceEvent)
        return (
            <div className="font-semibold text-xs">
                {perfSections
                    .filter((x) => x != 'server_timing')
                    .map((section) => {
                        const matchedSection = performanceMeasures.networkTimings[section]
                        return matchedSection ? (
                            <TimingBar
                                key={section}
                                section={section}
                                matchedSection={matchedSection}
                                rangeStart={rangeStart}
                                rangeEnd={rangeEnd}
                            />
                        ) : null
                    })}
                {performanceMeasures['serverTimings'].length > 0 ? (
                    <>
                        <LemonDivider dashed={true} />
                        <Tooltip title={perfDescriptions['server_timing']}>
                            <h3 className="text-sm text-muted">Server timings</h3>
                        </Tooltip>
                        {performanceMeasures.serverTimings.map((timing) => {
                            return timing ? (
                                <TimingBar
                                    key={timing.label}
                                    section="server_timing"
                                    matchedSection={timing}
                                    rangeStart={rangeStart}
                                    rangeEnd={rangeEnd}
                                />
                            ) : null
                        })}
                    </>
                ) : null}
            </div>
        )
    }
    return null
}
