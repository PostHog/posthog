import { useValues } from 'kea'

import { TZLabel } from 'lib/components/TZLabel'
import { PlayerInspectorBottomSettings } from 'scenes/session-recordings/player/inspector/PlayerInspectorBottomSettings'
import { PlayerInspectorControls } from 'scenes/session-recordings/player/inspector/PlayerInspectorControls'
import { PlayerInspectorList } from 'scenes/session-recordings/player/inspector/PlayerInspectorList'
import { sessionEventsDataLogic } from 'scenes/session-recordings/player/sessionEventsDataLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'

export function PlayerInspector(): JSX.Element {
    // The player can swap recordings without remounting this component, and a React error boundary
    // holds its failed state until it unmounts. Key the boundary on the recording so a new recording
    // remounts it and clears a stale fallback from an earlier crash.
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { eventsOutsideWindow } = useValues(sessionEventsDataLogic(logicProps))
    return (
        <>
            <PlayerInspectorControls />
            {eventsOutsideWindow ? (
                <div className="py-1.5 px-2 border-b text-xs text-secondary text-balance">
                    {eventsOutsideWindow.count} events of this session are dated outside the recording, so they are not
                    listed here. The oldest is from <TZLabel time={eventsOutsideWindow.earliest} />. A wrong clock on
                    the device usually causes this.
                </div>
            ) : null}
            {/* Only the list is wrapped, so a crashing row leaves the filters that navigate around it usable. */}
            <ErrorBoundary key={sessionRecordingId} exceptionProps={{ feature: 'replay-inspector' }}>
                <PlayerInspectorList />
            </ErrorBoundary>
            <PlayerInspectorBottomSettings />
        </>
    )
}
