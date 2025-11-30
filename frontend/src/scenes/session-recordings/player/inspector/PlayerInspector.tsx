import { PlayerInspectorBottomSettings } from 'scenes/session-recordings/player/inspector/PlayerInspectorBottomSettings'
import { PlayerInspectorControls } from 'scenes/session-recordings/player/inspector/PlayerInspectorControls'
import { PlayerInspectorList } from 'scenes/session-recordings/player/inspector/PlayerInspectorList'

export function PlayerInspector(): JSX.Element {
    return (
        <div className="flex flex-col flex-1 min-h-0">
            <PlayerInspectorControls />
            <div className="flex-1 min-h-0 relative flex flex-col">
                <PlayerInspectorList />
            </div>
            <PlayerInspectorBottomSettings />
        </div>
    )
}
