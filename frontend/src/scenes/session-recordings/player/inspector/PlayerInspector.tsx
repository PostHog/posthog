import { BindLogic } from 'kea'
import { PlayerInspectorBottomSettings } from 'scenes/session-recordings/player/inspector/PlayerInspectorBottomSettings'
import { PlayerInspectorControls } from 'scenes/session-recordings/player/inspector/PlayerInspectorControls'
import { PlayerInspectorList } from 'scenes/session-recordings/player/inspector/PlayerInspectorList'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { SessionRecordingPlayerLogicKey } from 'scenes/session-recordings/types'

export function PlayerInspector(props: SessionRecordingPlayerLogicKey): JSX.Element {
    return props.sessionRecordingId ? (
        <BindLogic logic={sessionRecordingPlayerLogic} props={props}>
            <PlayerInspectorControls />
            <PlayerInspectorList />
            <PlayerInspectorBottomSettings />
        </BindLogic>
    ) : (
        <>some empty message</>
    )
}
