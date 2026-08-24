import { useValues } from 'kea'

import { PlayerInspectorBottomSettings } from 'scenes/session-recordings/player/inspector/PlayerInspectorBottomSettings'
import { PlayerInspectorControls } from 'scenes/session-recordings/player/inspector/PlayerInspectorControls'
import { PlayerInspectorList } from 'scenes/session-recordings/player/inspector/PlayerInspectorList'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'

export function PlayerInspector(): JSX.Element {
    // The player can swap recordings without remounting this component, and a React error boundary
    // holds its failed state until it unmounts. Key the boundary on the recording so a new recording
    // remounts it and clears a stale fallback from an earlier crash.
    const { sessionRecordingId } = useValues(sessionRecordingPlayerLogic)
    return (
        <ErrorBoundary key={sessionRecordingId} exceptionProps={{ feature: 'replay-inspector' }}>
            <PlayerInspectorControls />
            <PlayerInspectorList />
            <PlayerInspectorBottomSettings />
        </ErrorBoundary>
    )
}
