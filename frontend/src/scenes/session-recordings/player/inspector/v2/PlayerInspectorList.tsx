import { useValues } from 'kea'
import { SessionRecordingPlayerLogicProps } from '../../sessionRecordingPlayerLogic'
import { sharedListLogic } from '../sharedListLogic'
import { ItemPerformanceEvent } from './components/ItemPerformanceEvent'

export function PlayerInspectorList(props: SessionRecordingPlayerLogicProps): JSX.Element {
    const { items } = useValues(sharedListLogic(props))

    return (
        <div className="flex flex-col bg-side flex-1 overflow-hidden relative">
            <ul className="flex-1 overflow-y-auto absolute inset-0">
                {items.map((item, i) => (
                    <li key={i}>{item.type === 'performance' && <ItemPerformanceEvent item={item.data} />}</li>
                ))}
            </ul>
        </div>
    )
}
