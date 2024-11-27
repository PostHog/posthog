import {
    BaseIcon,
    IconBolt,
    IconChat,
    IconCloud,
    IconCursor,
    IconDashboard,
    IconEye,
    IconGear,
    IconLeave,
    IconLogomark,
    IconMinusSquare,
    IconPlusSquare,
    IconTerminal,
} from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Dayjs } from 'lib/dayjs'
import useIsHovering from 'lib/hooks/useIsHovering'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from 'lib/taxonomy'
import { ceilMsToClosestSecond, colonDelimitedDuration } from 'lib/utils'
import { useEffect, useRef } from 'react'
import { ItemComment, ItemCommentDetail } from 'scenes/session-recordings/player/inspector/components/ItemComment'
import { ItemInactivity } from 'scenes/session-recordings/player/inspector/components/ItemInactivity'
import { ItemSummary } from 'scenes/session-recordings/player/inspector/components/ItemSummary'
import { useDebouncedCallback } from 'use-debounce'
import useResizeObserver from 'use-resize-observer'

import { FilterableInspectorListItemTypes } from '~/types'

import { ItemPerformanceEvent, ItemPerformanceEventDetail } from '../../../apm/playerInspector/ItemPerformanceEvent'
import { IconWindow } from '../../icons'
import { playerSettingsLogic, TimestampFormat } from '../../playerSettingsLogic'
import { sessionRecordingPlayerLogic } from '../../sessionRecordingPlayerLogic'
import { InspectorListItem, playerInspectorLogic } from '../playerInspectorLogic'
import { ItemConsoleLog, ItemConsoleLogDetail } from './ItemConsoleLog'
import { ItemDoctor, ItemDoctorDetail } from './ItemDoctor'
import { ItemEvent, ItemEventDetail } from './ItemEvent'

const PLAYER_INSPECTOR_LIST_ITEM_MARGIN = 1

const typeToIconAndDescription = {
    [FilterableInspectorListItemTypes.EVENTS]: {
        Icon: undefined,
        tooltip: 'Recording event',
    },
    [FilterableInspectorListItemTypes.CONSOLE]: {
        Icon: IconTerminal,
        tooltip: 'Console log',
    },
    [FilterableInspectorListItemTypes.NETWORK]: {
        Icon: IconDashboard,
        tooltip: 'Network event',
    },
    ['offline-status']: {
        Icon: IconCloud,
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
        Icon: IconChat,
        tooltip: 'A user commented on this timestamp in the recording',
    },
    ['inspector-summary']: {
        Icon: undefined,
        tooltip: undefined,
    },
    ['inactivity']: {
        Icon: undefined,
        tooltip: undefined,
    },
}

// TODO @posthog/icons doesn't export the type we need here
// eslint-disable-next-line @typescript-eslint/explicit-module-boundary-types,@typescript-eslint/explicit-function-return-type
export function eventToIcon(event: string | undefined | null) {
    switch (event) {
        case '$pageview':
            return IconEye
        case '$screen':
            return IconEye
        case '$pageleave':
            return IconLeave
        case '$autocapture':
            return IconBolt
    }

    if (event && !!CORE_FILTER_DEFINITIONS_BY_GROUP.events[event]) {
        return IconLogomark
    }

    // technically we should have the select all icon for "All events" completeness,
    // but we never actually display it, and it messes up the type signatures for the icons
    if (event === null) {
        return BaseIcon
    }

    if (event !== undefined) {
        return IconCursor
    }

    return BaseIcon
}

function ItemTimeDisplay({ item }: { item: InspectorListItem }): JSX.Element {
    const { timestampFormat } = useValues(playerSettingsLogic)
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { durationMs } = useValues(playerInspectorLogic(logicProps))

    const fixedUnits = durationMs / 1000 > 3600 ? 3 : 2

    return (
        <span className="px-2 py-1 text-xs min-w-18 text-center">
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
}: {
    item: InspectorListItem
    finalTimestamp: Dayjs | null
}): JSX.Element {
    return (
        <div className="flex items-center text-text-3000" data-attr="row-item-title">
            {item.type === FilterableInspectorListItemTypes.NETWORK ? (
                <ItemPerformanceEvent item={item.data} finalTimestamp={finalTimestamp} />
            ) : item.type === FilterableInspectorListItemTypes.CONSOLE ? (
                <ItemConsoleLog item={item} />
            ) : item.type === FilterableInspectorListItemTypes.EVENTS ? (
                <ItemEvent item={item} />
            ) : item.type === 'offline-status' ? (
                <div className="flex w-full items-start p-2 text-xs font-light font-mono">
                    {item.offline ? 'Browser went offline' : 'Browser returned online'}
                </div>
            ) : item.type === 'browser-visibility' ? (
                <div className="flex w-full items-start px-2 py-1 font-light font-mono text-xs">
                    Window became {item.status}
                </div>
            ) : item.type === FilterableInspectorListItemTypes.DOCTOR ? (
                <ItemDoctor item={item} />
            ) : item.type === 'comment' ? (
                <ItemComment item={item} />
            ) : item.type === 'inspector-summary' ? (
                <ItemSummary item={item} />
            ) : item.type === 'inactivity' ? (
                <ItemInactivity item={item} />
            ) : null}
        </div>
    )
}

function RowItemDetail({
    item,
    finalTimestamp,
    onClick,
}: {
    item: InspectorListItem
    finalTimestamp: Dayjs | null
    onClick: () => void
}): JSX.Element | null {
    return (
        <div onClick={onClick}>
            {item.type === FilterableInspectorListItemTypes.NETWORK ? (
                <ItemPerformanceEventDetail item={item.data} finalTimestamp={finalTimestamp} />
            ) : item.type === FilterableInspectorListItemTypes.CONSOLE ? (
                <ItemConsoleLogDetail item={item} />
            ) : item.type === FilterableInspectorListItemTypes.EVENTS ? (
                <ItemEventDetail item={item} />
            ) : item.type === 'offline-status' ? null : item.type === 'browser-visibility' ? null : item.type ===
              FilterableInspectorListItemTypes.DOCTOR ? (
                <ItemDoctorDetail item={item} />
            ) : item.type === 'comment' ? (
                <ItemCommentDetail item={item} />
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
    const hoverRef = useRef<HTMLDivElement>(null)

    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { seekToTime } = useActions(sessionRecordingPlayerLogic)

    const { end, expandedItems } = useValues(playerInspectorLogic(logicProps))
    const { setItemExpanded } = useActions(playerInspectorLogic(logicProps))

    const isExpanded = expandedItems.includes(index)

    // NOTE: We offset by 1 second so that the playback starts just before the event occurs.
    // Ceiling second is used since this is what's displayed to the user.
    const seekToEvent = (): void => seekToTime(ceilMsToClosestSecond(item.timeInRecording) - 1000)

    const onLayoutDebounced = useDebouncedCallback(onLayout, 500)
    const { ref, width, height } = useResizeObserver({})

    const totalHeight = height ? height + PLAYER_INSPECTOR_LIST_ITEM_MARGIN : height

    // Height changes should lay out immediately but width ones (browser resize can be much slower)
    useEffect(
        () => {
            if (!width || !totalHeight) {
                return
            }
            onLayoutDebounced({ width, height: totalHeight })
        },
        // purposefully only triggering on width
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [width]
    )

    useEffect(
        () => {
            if (!width || !totalHeight) {
                return
            }
            onLayout({ width, height: totalHeight })
        },
        // purposefully only triggering on total height
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [totalHeight]
    )

    const isHovering = useIsHovering(hoverRef)

    let TypeIcon = typeToIconAndDescription[item.type].Icon
    if (TypeIcon === undefined && item.type === FilterableInspectorListItemTypes.EVENTS) {
        // KLUDGE this is a hack to lean on this function, yuck
        TypeIcon = eventToIcon(item.data.event)
    }

    return (
        <div
            ref={ref}
            className={clsx(
                'ml-1 flex flex-col items-center',
                isExpanded && 'border border-primary',
                isExpanded && item.highlightColor && `border border-${item.highlightColor}-dark`,
                isHovering && 'bg-bg-light'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                zIndex: isExpanded ? 1 : 0,
            }}
        >
            <div className="flex flex-row items-center w-full px-1">
                <div
                    className="flex flex-row flex-1 items-center overflow-hidden cursor-pointer"
                    ref={hoverRef}
                    onClick={() => seekToEvent()}
                >
                    {/*TODO this tooltip doesn't trigger whether its inside or outside of this hover container */}
                    {item.windowNumber ? (
                        <Tooltip
                            placement="left"
                            title={
                                <>
                                    <b>{typeToIconAndDescription[item.type]?.tooltip}</b>

                                    <>
                                        <br />
                                        {item.windowNumber !== '?' ? (
                                            <>
                                                {' '}
                                                occurred in Window <b>{item.windowNumber}</b>
                                            </>
                                        ) : (
                                            <>
                                                {' '}
                                                not linked to any specific window. Either an event tracked from the
                                                backend or otherwise not able to be linked to a given window.
                                            </>
                                        )}
                                    </>
                                </>
                            }
                        >
                            <IconWindow size="small" value={item.windowNumber || '?'} />
                        </Tooltip>
                    ) : null}

                    {item.type !== 'inspector-summary' && item.type !== 'inactivity' && <ItemTimeDisplay item={item} />}

                    {TypeIcon ? <TypeIcon /> : <BaseIcon className="min-w-4" />}

                    <div
                        className={clsx(
                            'flex-1 overflow-hidden',
                            item.highlightColor && `bg-${item.highlightColor}-highlight`
                        )}
                    >
                        <RowItemTitle item={item} finalTimestamp={end} />
                    </div>
                </div>
                {item.type !== 'inspector-summary' && item.type !== 'inactivity' && (
                    <LemonButton
                        icon={isExpanded ? <IconMinusSquare /> : <IconPlusSquare />}
                        size="small"
                        noPadding
                        onClick={() => setItemExpanded(index, !isExpanded)}
                        data-attr="expand-inspector-row"
                        disabledReason={
                            item.type === 'offline-status' || item.type === 'browser-visibility'
                                ? 'This event type does not have a detail view'
                                : undefined
                        }
                    />
                )}
            </div>

            {isExpanded ? (
                <div
                    className={clsx(
                        'w-full mx-2 overflow-hidden',
                        item.highlightColor && `bg-${item.highlightColor}-highlight`
                    )}
                >
                    <div className="text-xs">
                        <RowItemDetail item={item} finalTimestamp={end} onClick={() => seekToEvent()} />
                        <LemonDivider dashed />

                        <div
                            className="flex justify-end cursor-pointer mx-2 my-1"
                            onClick={() => setItemExpanded(index, false)}
                        >
                            <span className="text-muted-alt">Collapse</span>
                        </div>
                    </div>
                </div>
            ) : null}
        </div>
    )
}
