import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import {
    PerformanceMeasures,
    TimingBar,
    calculatePerformanceParts,
    perfDescriptions,
    perfSections,
} from 'scenes/session-recordings/apm/waterfall/TimingBar'

import { PerformanceEvent } from '~/types'

export const convertForTimelineView = (
    performanceEvent: PerformanceEvent
): {
    rangeStart: number | undefined
    rangeEnd: number | undefined
    performanceMeasures: PerformanceMeasures | null
    isValid: boolean
} => {
    const rangeStart = performanceEvent.start_time
    const rangeEnd = performanceEvent.load_event_end
        ? performanceEvent.load_event_end
        : performanceEvent.response_end
          ? performanceEvent.response_end
          : performanceEvent.end_time
    const performanceMeasures =
        typeof rangeStart === 'number' && typeof rangeEnd === 'number'
            ? calculatePerformanceParts(performanceEvent)
            : null
    const performanceMeasuresIsEmpty =
        performanceMeasures === null ||
        (Object.keys(performanceMeasures.networkTimings).length === 0 && performanceMeasures.serverTimings.length === 0)
    return {
        rangeStart,
        rangeEnd,
        performanceMeasures,
        isValid: performanceMeasures !== null && !performanceMeasuresIsEmpty,
    }
}

/**
 * When displaying a waterfall view
 * we can show the parts that make up a performance entry
 */
export const TimeLineView = ({ performanceEvent }: { performanceEvent: PerformanceEvent }): JSX.Element | null => {
    const { rangeStart, rangeEnd, performanceMeasures, isValid } = convertForTimelineView(performanceEvent)

    if (!performanceMeasures || !isValid || rangeStart === undefined || rangeEnd === undefined) {
        return null
    }

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
                        <h3 className="text-sm text-secondary">Server timings</h3>
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
