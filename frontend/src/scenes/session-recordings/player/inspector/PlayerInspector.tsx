import { PlayerInspectorBottomSettings } from 'scenes/session-recordings/player/inspector/PlayerInspectorBottomSettings'
import { PlayerInspectorControls } from 'scenes/session-recordings/player/inspector/PlayerInspectorControls'
import { PlayerInspectorList } from 'scenes/session-recordings/player/inspector/PlayerInspectorList'

import { ErrorBoundary } from '~/layout/ErrorBoundary'

export function PlayerInspector(): JSX.Element {
    return (
        <ErrorBoundary exceptionProps={{ feature: 'replay-inspector' }}>
            <PlayerInspectorControls />
            <PlayerInspectorList />
            <PlayerInspectorBottomSettings />
        </ErrorBoundary>
    )
}
