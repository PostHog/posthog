import { LemonDivider } from '@posthog/lemon-ui'
import { SessionRecordingPlayerLogicProps } from '../sessionRecordingPlayerLogic'
import { PlayerInspectorList } from './PlayerInspectorList'
import { PlayerInspectorControls } from './PlayerInspectorControls'

export function PlayerInspector(props: SessionRecordingPlayerLogicProps): JSX.Element {
    return (
        <>
            <PlayerInspectorControls {...props} />
            <LemonDivider className="my-0" />
            <PlayerInspectorList {...props} />
        </>
    )
}
