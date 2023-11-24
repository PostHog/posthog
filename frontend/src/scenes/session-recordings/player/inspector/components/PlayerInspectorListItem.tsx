import { TZLabel } from '@posthog/apps-common'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconGauge, IconTerminal, IconUnverifiedEvent } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { ceilMsToClosestSecond, colonDelimitedDuration } from 'lib/utils'
import { useEffect } from 'react'
import { useDebouncedCallback } from 'use-debounce'
import useResizeObserver from 'use-resize-observer'

import { SessionRecordingPlayerTab } from '~/types'

import { IconWindow } from '../../icons'
import { playerSettingsLogic } from '../../playerSettingsLogic'
import { sessionRecordingPlayerLogic } from '../../sessionRecordingPlayerLogic'
import { InspectorListItem, playerInspectorLogic } from '../playerInspectorLogic'
import { ItemConsoleLog } from './ItemConsoleLog'
import { ItemEvent } from './ItemEvent'
import { ItemPerformanceEvent } from './ItemPerformanceEvent'

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
        Icon: IconGauge,
        tooltip: 'Network event',
    },
}
const PLAYER_INSPECTOR_LIST_ITEM_MARGIN = 4

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
    const { tab, durationMs, end, expandedItems, windowIds } = useValues(playerInspectorLogic(logicProps))
    const { timestampMode } = useValues(playerSettingsLogic)

    const { seekToTime } = useActions(sessionRecordingPlayerLogic)
    const { setItemExpanded } = useActions(playerInspectorLogic(logicProps))
    const showIcon = tab === SessionRecordingPlayerTab.ALL
    const fixedUnits = durationMs / 1000 > 3600 ? 3 : 2

    const isExpanded = expandedItems.includes(index)

    // NOTE: We offset by 1 second so that the playback starts just before the event occurs.
    // Ceiling second is used since this is what's displayed to the user.
    const seekToEvent = (): void => seekToTime(ceilMsToClosestSecond(item.timeInRecording) - 1000)

    const itemProps = {
        setExpanded: () => {
            setItemExpanded(index, !isExpanded)
            if (!isExpanded) {
                seekToEvent()
            }
        },
        expanded: isExpanded,
    }

    const onLayoutDebounced = useDebouncedCallback(onLayout, 500)
    const { ref, width, height } = useResizeObserver({})

    const totalHeight = height ? height + PLAYER_INSPECTOR_LIST_ITEM_MARGIN : height

    // Height changes should layout immediately but width ones (browser resize can be much slower)
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
            className={clsx('flex flex-1 overflow-hidden gap-2 relative items-start')}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                // Style as we need it for the layout optimisation
                marginTop: PLAYER_INSPECTOR_LIST_ITEM_MARGIN / 2,
                marginBottom: PLAYER_INSPECTOR_LIST_ITEM_MARGIN / 2,
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

            <span
                className={clsx(
                    'flex-1 overflow-hidden rounded border',
                    isExpanded && 'border-primary',
                    item.highlightColor && `border-${item.highlightColor}-dark bg-${item.highlightColor}-highlight`,
                    !item.highlightColor && 'bg-bg-light'
                )}
            >
                {item.type === SessionRecordingPlayerTab.NETWORK ? (
                    <ItemPerformanceEvent item={item.data} finalTimestamp={end} {...itemProps} />
                ) : item.type === SessionRecordingPlayerTab.CONSOLE ? (
                    <ItemConsoleLog item={item} {...itemProps} />
                ) : item.type === SessionRecordingPlayerTab.EVENTS ? (
                    <ItemEvent item={item} {...itemProps} />
                ) : null}

                {isExpanded ? (
                    <div className="text-xs">
                        <LemonDivider dashed />

                        <div
                            className="flex gap-2 justify-end cursor-pointer m-2"
                            onClick={() => setItemExpanded(index, false)}
                        >
                            <span className="text-muted-alt">Collapse</span>
                        </div>
                    </div>
                ) : null}
            </span>
            {!isExpanded ? (
                <LemonButton size="small" noPadding status="primary-alt" onClick={() => seekToEvent()}>
                    <span className="p-1 text-xs">
                        {timestampMode === 'absolute' ? (
                            <TZLabel time={item.timestamp} formatDate="DD, MMM" formatTime="HH:mm:ss" noStyles />
                        ) : (
                            <>
                                {item.timeInRecording < 0 ? (
                                    <Tooltip
                                        title="This event occured before the recording started, likely as the page was loading."
                                        placement="left"
                                    >
                                        {colonDelimitedDuration(item.timeInRecording / 1000, fixedUnits)}
                                    </Tooltip>
                                ) : (
                                    colonDelimitedDuration(item.timeInRecording / 1000, fixedUnits)
                                )}
                            </>
                        )}
                    </span>
                </LemonButton>
            ) : null}
        </div>
    )
}
