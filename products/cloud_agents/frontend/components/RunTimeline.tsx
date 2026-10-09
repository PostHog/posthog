import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonCard, Spinner } from '@posthog/lemon-ui'

import { cloudAgentRunLogic } from '../logics/cloudAgentRunLogic'
import { LoadErrorBanner } from './LoadErrorBanner'
import { RunTimelineRow } from './RunTimelineRow'

/** What the agent said and did, oldest first. Renders the newest rows and shows earlier ones on request. */
export function RunTimeline(): JSX.Element {
    const {
        runEvents,
        runEventsLoading,
        runEventsLoadFailed,
        visibleTimelineRows,
        hiddenTimelineRowCount,
        eventsTruncated,
        isActive,
    } = useValues(cloudAgentRunLogic)
    const { loadRunEvents, showEarlierEvents } = useActions(cloudAgentRunLogic)

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4" data-attr="cloud-agents-run-timeline">
            <div className="flex items-center justify-between gap-2">
                <h3 className="m-0 text-base font-semibold">Timeline</h3>
                {isActive && <span className="text-secondary text-xs">Updates every few seconds</span>}
            </div>
            {runEvents === null && runEventsLoadFailed ? (
                <LoadErrorBanner what="the timeline" onRetry={loadRunEvents} retrying={runEventsLoading} />
            ) : runEvents === null ? (
                <div className="text-secondary flex items-center gap-2">
                    <Spinner /> Loading the timeline
                </div>
            ) : (
                <>
                    {eventsTruncated && (
                        <LemonBanner type="info">
                            This run has more events than this page can load, so the latest ones are missing.
                        </LemonBanner>
                    )}
                    {visibleTimelineRows.length === 0 ? (
                        <p className="m-0 text-secondary">
                            {isActive
                                ? 'No events yet. They show here when the agent starts work.'
                                : 'This run has no stored events.'}
                        </p>
                    ) : hiddenTimelineRowCount > 0 ? (
                        <LemonButton
                            type="secondary"
                            size="small"
                            className="self-start"
                            onClick={showEarlierEvents}
                            data-attr="cloud-agents-run-show-earlier"
                        >
                            Show earlier ({hiddenTimelineRowCount} more)
                        </LemonButton>
                    ) : null}
                    {visibleTimelineRows.length > 0 && (
                        <div className="flex flex-col gap-3">
                            {visibleTimelineRows.map((row) => (
                                <RunTimelineRow key={row.key} row={row} />
                            ))}
                        </div>
                    )}
                </>
            )}
        </LemonCard>
    )
}
