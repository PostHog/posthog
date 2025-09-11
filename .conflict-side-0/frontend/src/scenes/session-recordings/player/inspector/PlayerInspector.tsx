import { PlayerInspectorBottomSettings } from 'scenes/session-recordings/player/inspector/PlayerInspectorBottomSettings'
import { PlayerInspectorControls } from 'scenes/session-recordings/player/inspector/PlayerInspectorControls'
import { PlayerInspectorList } from 'scenes/session-recordings/player/inspector/PlayerInspectorList'

export function PlayerInspector(): JSX.Element {
    return (
        <>
            <PlayerInspectorControls />
            <PlayerInspectorList />
            <PlayerInspectorBottomSettings />
        </>
    )
}
