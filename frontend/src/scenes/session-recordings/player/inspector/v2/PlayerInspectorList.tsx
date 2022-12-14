import { useValues } from 'kea'
import { SessionRecordingPlayerLogicProps } from '../../sessionRecordingPlayerLogic'
import { sharedListLogic } from '../sharedListLogic'

export function PlayerInspectorList(props: SessionRecordingPlayerLogicProps): JSX.Element {
    const { tab } = useValues(sharedListLogic(props))

    return <p>{tab}!</p>
}
