import clsx from 'clsx'
import { useValues } from 'kea'
import { UnverifiedEvent, IconTerminal, IconGauge } from 'lib/components/icons'
import { colonDelimitedDuration } from 'lib/utils'
import { SessionRecordingPlayerTab } from '~/types'
import { SessionRecordingPlayerLogicProps } from '../../sessionRecordingPlayerLogic'
import { sharedListLogic } from '../sharedListLogic'
import { ItemConsoleLog } from './components/ItemConsoleLog'
import { ItemPerformanceEvent } from './components/ItemPerformanceEvent'

const TabToIcon = {
    [SessionRecordingPlayerTab.EVENTS]: <UnverifiedEvent />,
    [SessionRecordingPlayerTab.CONSOLE]: <IconTerminal />,
    [SessionRecordingPlayerTab.PERFORMANCE]: <IconGauge />,
}

export function PlayerInspectorList(props: SessionRecordingPlayerLogicProps): JSX.Element {
    const { tab, items, lastItemTimestamp, recordingTimeInfo } = useValues(sharedListLogic(props))
    const showIcon = tab === SessionRecordingPlayerTab.ALL

    const fixedUnits = recordingTimeInfo.duration / 1000 > 3600 ? 3 : 2

    return (
        <div className="flex flex-col bg-side flex-1 overflow-hidden relative">
            <ul className="flex-1 overflow-y-auto absolute inset-0 p-2">
                {items.map((item, i) => (
                    <li className={clsx('flex flex-1 overflow-hidden gap-2', i > 0 && 'mt-1')} key={i}>
                        {showIcon ? (
                            <span className="shrink-0 text-lg text-muted-alt h-8 w-5 text-center flex items-center justify-center">
                                {TabToIcon[item.type]}
                            </span>
                        ) : null}
                        <span className="flex-1 overflow-hidden">
                            {item.type === 'performance' ? (
                                <ItemPerformanceEvent item={item.data} finalTimestamp={lastItemTimestamp} />
                            ) : item.type === 'console' ? (
                                <ItemConsoleLog item={item} />
                            ) : null}
                        </span>
                        <span className="shrink-0 text-muted-alt mt-2 text-center text-xs cursor-pointer">
                            {item.timeInRecording < 0
                                ? 'LOAD'
                                : colonDelimitedDuration(item.timeInRecording / 1000, fixedUnits)}
                            {}
                        </span>
                    </li>
                ))}
            </ul>
        </div>
    )
}
