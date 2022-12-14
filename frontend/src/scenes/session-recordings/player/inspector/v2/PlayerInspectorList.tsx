import clsx from 'clsx'
import { useValues } from 'kea'
import { SessionRecordingPlayerLogicProps } from '../../sessionRecordingPlayerLogic'
import { sharedListLogic } from '../sharedListLogic'
import { ItemPerformanceEvent } from './components/ItemPerformanceEvent'

export function PlayerInspectorList(props: SessionRecordingPlayerLogicProps): JSX.Element {
    const { items, lastItemTimestamp } = useValues(sharedListLogic(props))

    return (
        <div className="flex flex-col bg-side flex-1 overflow-hidden relative">
            <ul className="flex-1 overflow-y-auto absolute inset-0 p-2">
                {items.map((item, i) => (
                    <li className={clsx(i > 0 && 'mt-1')} key={i}>
                        {item.type === 'performance' && (
                            <ItemPerformanceEvent item={item.data} finalTimestamp={lastItemTimestamp} />
                        )}
                    </li>
                ))}
            </ul>
        </div>
    )
}
