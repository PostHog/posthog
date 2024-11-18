import { PlayerInspectorControls } from 'scenes/session-recordings/player/inspector/PlayerInspectorControls'
import { PlayerInspectorList } from 'scenes/session-recordings/player/inspector/PlayerInspectorList'

export function PlayerInspector(): JSX.Element {
    return (
        <>
            <PlayerInspectorControls />
            <PlayerInspectorList />
        </>
    )
}
