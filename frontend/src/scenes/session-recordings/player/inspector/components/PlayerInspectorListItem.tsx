import { IconDashboard, IconEye, IconGear, IconMinusSquare, IconPlusSquare, IconTerminal } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Dayjs } from 'lib/dayjs'
import { IconComment, IconOffline, IconUnverifiedEvent } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { ceilMsToClosestSecond, colonDelimitedDuration } from 'lib/utils'
import { useEffect } from 'react'
import { ItemComment } from 'scenes/session-recordings/player/inspector/components/ItemComment'
import { useDebouncedCallback } from 'use-debounce'
import useResizeObserver from 'use-resize-observer'

import { SessionRecordingPlayerTab } from '~/types'

import { ItemPerformanceEvent } from '../../../apm/playerInspector/ItemPerformanceEvent'
import { IconWindow } from '../../icons'
import { playerSettingsLogic, TimestampFormat } from '../../playerSettingsLogic'
import { sessionRecordingPlayerLogic } from '../../sessionRecordingPlayerLogic'
import { InspectorListItem, playerInspectorLogic } from '../playerInspectorLogic'
import { ItemConsoleLog } from './ItemConsoleLog'
import { ItemDoctor } from './ItemDoctor'
import { ItemEvent } from './ItemEvent'

const typeToIconAndDescription = {
    [SessionRecordingPlayerTab.ALL]: {
        Icon: undefined,
        tooltip: 'All events',
    },
    [SessionRecordingPlayerTab.EVENTS]: {
        Icon: IconUnverifiedEvent,
        tooltip: 'Recording event',
    },
    [SessionRecordingPlayerTab.CONSOLE]: {
        Icon: IconTerminal,
        tooltip: 'Console log',
    },
    [SessionRecordingPlayerTab.NETWORK]: {
        Icon: IconDashboard,
        tooltip: 'Network event',
    },
    ['offline-status']: {
        Icon: IconOffline,
        tooltip: 'browser went offline or returned online',
    },
    ['browser-visibility']: {
        Icon: IconEye,
        tooltip: 'browser tab/window became visible or hidden',
    },
    ['$session_config']: {
        Icon: IconGear,
        tooltip: 'Session recording config',
    },
    ['doctor']: {
        Icon: undefined,
        tooltip: 'Doctor event',
    },
    ['comment']: {
        Icon: IconComment,
        tooltip: 'A user commented on this timestamp in the recording',
    },
}
const PLAYER_INSPECTOR_LIST_ITEM_MARGIN = 1

function ItemTimeDisplay({ item }: { item: InspectorListItem }): JSX.Element {
    const { timestampFormat } = useValues(playerSettingsLogic)
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { durationMs } = useValues(playerInspectorLogic(logicProps))

    const fixedUnits = durationMs / 1000 > 3600 ? 3 : 2

    return (
        <span className="p-1 text-xs">
            {timestampFormat != TimestampFormat.Relative ? (
                (timestampFormat === TimestampFormat.UTC ? item.timestamp.tz('UTC') : item.timestamp).format(
                    'DD, MMM HH:mm:ss'
                )
            ) : (
                <>
                    {item.timeInRecording < 0 ? (
                        <Tooltip
                            title="This event occured before the recording started, likely as the page was loading."
                            placement="left"
                        >
                            <span className="text-muted">load</span>
                        </Tooltip>
                    ) : (
                        colonDelimitedDuration(item.timeInRecording / 1000, fixedUnits)
                    )}
                </>
            )}
        </span>
    )
}

function RowItemTitle({
    item,
    finalTimestamp,
    onClick,
    expanded,
}: {
    item: InspectorListItem
    finalTimestamp: Dayjs | null
    onClick: () => void
    expanded: boolean
}): JSX.Element {
    return (
        <div onClick={onClick}>
            {item.type === SessionRecordingPlayerTab.NETWORK ? (
                <ItemPerformanceEvent item={item.data} finalTimestamp={finalTimestamp} expanded={expanded} />
            ) : item.type === SessionRecordingPlayerTab.CONSOLE ? (
                <ItemConsoleLog item={item} expanded={expanded} />
            ) : item.type === SessionRecordingPlayerTab.EVENTS ? (
                <ItemEvent item={item} expanded={expanded} />
            ) : item.type === 'offline-status' ? (
                <div className="flex items-start p-2 text-xs">
                    {item.offline ? 'Browser went offline' : 'Browser returned online'}
                </div>
            ) : item.type === 'browser-visibility' ? (
                <div className="flex items-start p-2 text-xs">Window became {item.status}</div>
            ) : item.type === SessionRecordingPlayerTab.DOCTOR ? (
                <ItemDoctor item={item} expanded={expanded} />
            ) : item.type === 'comment' ? (
                <ItemComment item={item} expanded={expanded} />
            ) : null}
        </div>
    )
}

export function PlayerInspectorListItem({
    item,
    index,
    onLayout,
}: {
    item: InspectorListItem
    index: number
    onLayout: (layout: { width: number; height: number }) => void
}): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { seekToTime } = useActions(sessionRecordingPlayerLogic)

    const { tab, end, expandedItems, windowIds } = useValues(playerInspectorLogic(logicProps))
    const { setItemExpanded } = useActions(playerInspectorLogic(logicProps))

    const showIcon = tab === SessionRecordingPlayerTab.ALL

    const isExpanded = expandedItems.includes(index)

    // NOTE: We offset by 1 second so that the playback starts just before the event occurs.
    // Ceiling second is used since this is what's displayed to the user.
    const seekToEvent = (): void => seekToTime(ceilMsToClosestSecond(item.timeInRecording) - 1000)

    const onLayoutDebounced = useDebouncedCallback(onLayout, 500)
    const { ref, width, height } = useResizeObserver({})

    const totalHeight = height ? height + PLAYER_INSPECTOR_LIST_ITEM_MARGIN : height

    // Height changes should lay out immediately but width ones (browser resize can be much slower)
    useEffect(() => {
        if (!width || !totalHeight) {
            return
        }
        onLayoutDebounced({ width, height: totalHeight })
    }, [width])

    useEffect(() => {
        if (!width || !totalHeight) {
            return
        }
        onLayout({ width, height: totalHeight })
    }, [totalHeight])

    const windowNumber =
        windowIds.length > 1 ? (item.windowId ? windowIds.indexOf(item.windowId) + 1 || '?' : '?') : undefined

    const TypeIcon = typeToIconAndDescription[item.type].Icon

    return (
        <div
            ref={ref}
            className={clsx('flex flex-1 overflow-hidden relative items-start')}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                zIndex: isExpanded ? 1 : 0,
            }}
        >
            {!isExpanded && (showIcon || windowNumber) && (
                <Tooltip
                    placement="left"
                    title={
                        <>
                            <b>{typeToIconAndDescription[item.type]?.tooltip}</b>

                            {windowNumber ? (
                                <>
                                    <br />
                                    {windowNumber !== '?' ? (
                                        <>
                                            {' '}
                                            occurred in Window <b>{windowNumber}</b>
                                        </>
                                    ) : (
                                        <>
                                            {' '}
                                            not linked to any specific window. Either an event tracked from the backend
                                            or otherwise not able to be linked to a given window.
                                        </>
                                    )}
                                </>
                            ) : null}
                        </>
                    }
                >
                    <div className="shrink-0 text-2xl h-8 text-muted-alt flex items-center justify-center gap-1">
                        {showIcon && TypeIcon ? <TypeIcon /> : null}
                        {windowNumber ? <IconWindow size="small" value={windowNumber} /> : null}
                    </div>
                </Tooltip>
            )}

            <ItemTimeDisplay item={item} />

            <span
                className={clsx(
                    'flex-1 overflow-hidden rounded border',
                    isExpanded && 'border-primary',
                    item.highlightColor && `border-${item.highlightColor}-dark bg-${item.highlightColor}-highlight`,
                    !item.highlightColor && 'bg-bg-light'
                )}
            >
                <RowItemTitle item={item} finalTimestamp={end} onClick={() => seekToEvent()} expanded={isExpanded} />

                {isExpanded ? (
                    <div className="text-xs">
                        <LemonDivider dashed />

                        <div
                            className="flex justify-end cursor-pointer mx-2 my-1"
                            onClick={() => setItemExpanded(index, false)}
                        >
                            <span className="text-muted-alt">Collapse</span>
                        </div>
                    </div>
                ) : null}
            </span>

            <LemonButton
                icon={isExpanded ? <IconMinusSquare /> : <IconPlusSquare />}
                size="small"
                noPadding
                onClick={() => setItemExpanded(index, !isExpanded)}
                data-attr="expand-inspector-row"
            />
        </div>
    )
}
