import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { FunctionComponent, isValidElement, memo, useEffect, useRef } from 'react'
import { useDebouncedCallback } from 'use-debounce'
import useResizeObserver from 'use-resize-observer'

import {
    BaseIcon,
    IconBolt,
    IconChat,
    IconCloud,
    IconCollapse,
    IconCursor,
    IconDashboard,
    IconExpand,
    IconEye,
    IconGear,
    IconLeave,
    IconLogomark,
    IconRedux,
    IconTerminal,
} from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { Dayjs } from 'lib/dayjs'
import useIsHovering from 'lib/hooks/useIsHovering'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { ceilMsToClosestSecond, objectsEqual } from 'lib/utils'
import { ItemTimeDisplay } from 'scenes/session-recordings/components/ItemTimeDisplay'
import {
    ItemAnyComment,
    ItemAnyCommentDetail,
} from 'scenes/session-recordings/player/inspector/components/ItemAnyComment'
import { ItemInactivity } from 'scenes/session-recordings/player/inspector/components/ItemInactivity'
import { ItemSessionChange } from 'scenes/session-recordings/player/inspector/components/ItemSessionChange'
import { ItemSummary } from 'scenes/session-recordings/player/inspector/components/ItemSummary'

import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'

import { ItemPerformanceEvent, ItemPerformanceEventDetail } from '../../../apm/playerInspector/ItemPerformanceEvent'
import { IconWindow } from '../../icons'
import { sessionRecordingPlayerLogic } from '../../sessionRecordingPlayerLogic'
import { InspectorListItem, playerInspectorLogic } from '../playerInspectorLogic'
import { ItemAppState, ItemAppStateDetail, ItemConsoleLog, ItemConsoleLogDetail } from './ItemConsoleLog'
import { ItemDoctor, ItemDoctorDetail } from './ItemDoctor'
import { ItemEvent, ItemEventDetail, ItemEventMenu } from './ItemEvent'

const PLAYER_INSPECTOR_LIST_ITEM_MARGIN = 1

const typeToIconAndDescription = {
    events: {
        Icon: undefined,
        tooltip: 'Recording event',
    },
    console: {
        Icon: IconTerminal,
        tooltip: 'Console log',
    },
    'app-state': {
        Icon: IconRedux,
        tooltip: 'State log',
    },
    network: {
        Icon: IconDashboard,
        tooltip: 'Network event',
    },
    'offline-status': {
        Icon: IconCloud,
        tooltip: 'browser went offline or returned online',
    },
    'browser-visibility': {
        Icon: IconEye,
        tooltip: 'browser tab/window became visible or hidden',
    },
    $session_config: {
        Icon: IconGear,
        tooltip: 'Session recording config',
    },
    doctor: {
        Icon: undefined,
        tooltip: 'Doctor event',
    },
    comment: {
        Icon: IconChat,
        tooltip: 'A user commented on this timestamp in the recording',
    },
    annotation: {
        Icon: IconChat,
        tooltip: 'An annotation was added to this timestamp',
    },
    'inspector-summary': {
        Icon: undefined,
        tooltip: undefined,
    },
    inactivity: {
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

    // technically, we should have the select all icon for "All events" completeness,
    // but we never actually display it, and it messes up the type signatures for the icons
    if (event === null) {
        return BaseIcon
    }

    if (event !== undefined) {
        return IconCursor
    }

    return BaseIcon
}

function IconWithOptionalBadge({
    TypeIcon,
    showBadge = false,
}: {
    TypeIcon: FunctionComponent | undefined
    showBadge?: boolean
}): JSX.Element {
    if (!TypeIcon) {
        return <BaseIcon className="min-w-4" />
    }

    // If TypeIcon is already a JSX element (like the LemonBadge case), return as-is
    const iconElement = isValidElement(TypeIcon) ? TypeIcon : <TypeIcon />
    return showBadge ? (
        <div className="text-white bg-brand-blue rounded-full flex items-center p-0.5">{iconElement}</div>
    ) : (
        <div className="flex items-center p-0.5">{iconElement}</div>
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
            {item.type === 'network' ? (
                <ItemPerformanceEvent item={item.data} finalTimestamp={finalTimestamp} />
            ) : item.type === 'console' ? (
                <ItemConsoleLog item={item} />
            ) : item.type === 'app-state' ? (
                <ItemAppState item={item} />
            ) : item.type === 'events' ? (
                <ItemEvent item={item} />
            ) : item.type === 'offline-status' ? (
                <div className="flex w-full items-start p-2 text-xs font-light font-mono">
                    {item.offline ? 'Browser went offline' : 'Browser returned online'}
                </div>
            ) : item.type === 'browser-visibility' ? (
                <div className="flex w-full items-start px-2 py-1 font-light font-mono text-xs">
                    Window became {item.status}
                </div>
            ) : item.type === 'doctor' ? (
                <ItemDoctor item={item} />
            ) : item.type === 'comment' ? (
                <ItemAnyComment item={item} />
            ) : item.type === 'inspector-summary' ? (
                <ItemSummary item={item} />
            ) : item.type === 'inactivity' ? (
                <ItemInactivity item={item} />
            ) : item.type === 'session-change' ? (
                <ItemSessionChange item={item} />
            ) : null}
        </div>
    )
}

/**
 * Some items show a menu button in the item title bar when expanded.
 * For example to add sharing actions
 */
function RowItemMenu({ item }: { item: InspectorListItem }): JSX.Element | null {
    return item.type === 'events' ? <ItemEventMenu item={item} /> : null
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
            {item.type === 'network' ? (
                <ItemPerformanceEventDetail item={item.data} finalTimestamp={finalTimestamp} />
            ) : item.type === 'app-state' ? (
                <ItemAppStateDetail item={item} />
            ) : item.type === 'console' ? (
                <ItemConsoleLogDetail item={item} />
            ) : item.type === 'events' ? (
                <ItemEventDetail item={item} />
            ) : item.type === 'offline-status' ? null : item.type === 'browser-visibility' ? null : item.type ===
              'doctor' ? (
                <ItemDoctorDetail item={item} />
            ) : item.type === 'comment' ? (
                <ItemAnyCommentDetail item={item} />
            ) : null}
        </div>
    )
}

const ListItemTitle = memo(function ListItemTitle({
    item,
    index,
    hoverRef,
}: {
    item: InspectorListItem
    index: number
    hoverRef: React.RefObject<HTMLDivElement>
}) {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { seekToTime } = useActions(sessionRecordingPlayerLogic)

    const { end, expandedItems } = useValues(playerInspectorLogic(logicProps))
    const { setItemExpanded } = useActions(playerInspectorLogic(logicProps))

    const isExpanded = expandedItems.includes(index)

    // NOTE: We offset by 1 second so that the playback starts just before the event occurs.
    // Ceiling second is used since this is what's displayed to the user.
    const seekToEvent = (): void => seekToTime(ceilMsToClosestSecond(item.timeInRecording) - 1000)

    let TypeIcon = typeToIconAndDescription[item.type].Icon
    if (TypeIcon === undefined && item.type === 'events') {
        // KLUDGE this is a hack to lean on this function, yuck
        TypeIcon = eventToIcon(item.data.event)
    }

    return (
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
                                            not linked to any specific window. Either an event tracked from the backend
                                            or otherwise not able to be linked to a given window.
                                        </>
                                    )}
                                </>
                            </>
                        }
                    >
                        <IconWindow size="small" value={item.windowNumber || '?'} />
                    </Tooltip>
                ) : null}

                {item.type !== 'inspector-summary' && item.type !== 'inactivity' && (
                    <ItemTimeDisplay timestamp={item.timestamp} timeInRecording={item.timeInRecording} />
                )}

                <IconWithOptionalBadge TypeIcon={TypeIcon} showBadge={item.type === 'comment'} />

                <div
                    className={clsx(
                        'flex-1 overflow-hidden',
                        item.highlightColor === 'danger' && `bg-fill-error-highlight`,
                        item.highlightColor === 'warning' && `bg-fill-warning-highlight`,
                        item.highlightColor === 'primary' && `bg-fill-success-highlight`
                    )}
                >
                    <RowItemTitle item={item} finalTimestamp={end} />
                </div>
            </div>
            {isExpanded && <RowItemMenu item={item} />}
            {item.type !== 'inspector-summary' && item.type !== 'inactivity' && (
                <LemonButton
                    icon={isExpanded ? <IconCollapse /> : <IconExpand />}
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
    )
})

const ListItemDetail = memo(function ListItemDetail({ item, index }: { item: InspectorListItem; index: number }) {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { seekToTime } = useActions(sessionRecordingPlayerLogic)

    const { end } = useValues(playerInspectorLogic(logicProps))
    const { setItemExpanded } = useActions(playerInspectorLogic(logicProps))

    // NOTE: We offset by 1 second so that the playback starts just before the event occurs.
    // Ceiling second is used since this is what's displayed to the user.
    const seekToEvent = (): void => seekToTime(ceilMsToClosestSecond(item.timeInRecording) - 1000)

    return (
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
                    <span className="text-secondary">Collapse</span>
                </div>
            </div>
        </div>
    )
}, objectsEqual)

export const PlayerInspectorListItem = memo(function PlayerInspectorListItem({
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

    const { expandedItems } = useValues(playerInspectorLogic(logicProps))

    const isExpanded = expandedItems.includes(index)

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

    return (
        <div
            ref={ref}
            className={clsx(
                'ml-1 flex flex-col items-center',
                isExpanded && 'border border-accent',
                isExpanded && item.highlightColor && `border border-${item.highlightColor}-dark`,
                isHovering && 'bg-surface-primary'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                zIndex: isExpanded ? 1 : 0,
            }}
        >
            <ListItemTitle item={item} index={index} hoverRef={hoverRef} />

            {isExpanded ? <ListItemDetail item={item} index={index} /> : null}
        </div>
    )
}, objectsEqual)
