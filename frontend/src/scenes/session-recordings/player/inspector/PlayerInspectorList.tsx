import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconUnverifiedEvent, IconTerminal, IconGauge } from 'lib/lemon-ui/icons'
import { ceilMsToClosestSecond, colonDelimitedDuration } from 'lib/utils'
import { useEffect, useMemo, useRef } from 'react'
import { List, ListRowRenderer } from 'react-virtualized/dist/es/List'
import { CellMeasurer, CellMeasurerCache } from 'react-virtualized/dist/es/CellMeasurer'
import { AvailableFeature, SessionRecordingPlayerTab } from '~/types'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { InspectorListItem, playerInspectorLogic } from './playerInspectorLogic'
import { ItemConsoleLog } from './components/ItemConsoleLog'
import { ItemEvent } from './components/ItemEvent'
import { ItemPerformanceEvent } from './components/ItemPerformanceEvent'
import AutoSizer from 'react-virtualized/dist/es/AutoSizer'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { useDebouncedCallback } from 'use-debounce'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import './PlayerInspectorList.scss'
import { range } from 'd3'
import { teamLogic } from 'scenes/teamLogic'
import { openSessionRecordingSettingsDialog } from 'scenes/session-recordings/settings/SessionRecordingSettings'
import { playerSettingsLogic } from '../playerSettingsLogic'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { userLogic } from 'scenes/userLogic'
import { PayGatePage } from 'lib/components/PayGatePage/PayGatePage'
import { IconWindow } from 'scenes/session-recordings/player/icons'
import { TZLabel } from '@posthog/apps-common'

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

function PlayerInspectorListItem({
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

    const itemProps = {
        setExpanded: () => setItemExpanded(index, !isExpanded),
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
            className={clsx('flex flex-1 overflow-hidden gap-2 relative')}
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
                    !item.highlightColor && 'bg-inverse'
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
            {!isExpanded && (
                <LemonButton
                    size="small"
                    noPadding
                    status="primary-alt"
                    onClick={() => {
                        // NOTE: We offset by 1 second so that the playback starts just before the event occurs.
                        // Ceiling second is used since this is what's displayed to the user.
                        seekToTime(ceilMsToClosestSecond(item.timeInRecording) - 1000)
                    }}
                >
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
                                        LOAD
                                    </Tooltip>
                                ) : (
                                    colonDelimitedDuration(item.timeInRecording / 1000, fixedUnits)
                                )}
                            </>
                        )}
                    </span>
                </LemonButton>
            )}
        </div>
    )
}

function EmptyNetworkTab({
    captureNetworkLogOptIn,
    captureNetworkFeatureAvailable,
}: {
    captureNetworkLogOptIn: boolean
    captureNetworkFeatureAvailable: boolean
}): JSX.Element {
    return !captureNetworkFeatureAvailable ? (
        <div className="p-4">
            <PayGatePage
                featureKey={AvailableFeature.RECORDINGS_PERFORMANCE}
                featureName="Network Performance"
                header={
                    <>
                        Go deeper with <span className="highlight">Network Performance</span>!
                    </>
                }
                caption="Understand what is happening with network requests during your recordings to identify slow pages, API errors and more."
                docsLink="https://posthog.com/docs/user-guides/recordings"
            />
        </div>
    ) : !captureNetworkLogOptIn ? (
        <>
            <div className="flex flex-col items-center">
                <h4 className="text-xl font-medium">Performance events</h4>
                <p className="text-muted text-center">
                    Capture performance events like network requests during the browser recording to understand things
                    like response times, page load times, and more.
                </p>
                <LemonButton type="primary" onClick={() => openSessionRecordingSettingsDialog()} targetBlank>
                    Configure in settings
                </LemonButton>
            </div>
        </>
    ) : (
        <>No results found in this recording.</>
    )
}

function EmptyConsoleTab({ captureConsoleLogOptIn }: { captureConsoleLogOptIn: boolean }): JSX.Element {
    return captureConsoleLogOptIn ? (
        <>No results found in this recording.</>
    ) : (
        <>
            <div className="flex flex-col items-center">
                <h4 className="text-xl font-medium">Console logs</h4>
                <p className="text-muted text-center">
                    Capture all console logs during the browser recording to get technical information on what was
                    occurring.
                </p>
                <LemonButton type="primary" onClick={() => openSessionRecordingSettingsDialog()} targetBlank>
                    Configure in settings
                </LemonButton>
            </div>
        </>
    )
}

export function PlayerInspectorList(): JSX.Element {
    const { logicProps, fullLoad } = useValues(sessionRecordingPlayerLogic)
    const inspectorLogic = playerInspectorLogic(logicProps)

    const { items, tabsState, playbackIndicatorIndex, playbackIndicatorIndexStop, syncScrollingPaused, tab } =
        useValues(inspectorLogic)
    const { setSyncScrollPaused } = useActions(inspectorLogic)
    const { syncScroll } = useValues(playerSettingsLogic)
    const { currentTeam } = useValues(teamLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const performanceAvailable: boolean = hasAvailableFeature(AvailableFeature.RECORDINGS_PERFORMANCE)
    const performanceEnabled: boolean = currentTeam?.capture_performance_opt_in ?? false

    const cellMeasurerCache = useMemo(
        () =>
            new CellMeasurerCache({
                fixedWidth: true,
                minHeight: 10,
                defaultHeight: 40,
            }),
        []
    )

    const listRef = useRef<List | null>()
    const scrolledByJsFlag = useRef<boolean>(true)
    const mouseHoverRef = useRef<boolean>(false)

    // TRICKY: this is hacky but there is no other way to add a timestamp marker to the <List> component children
    // We want this as otherwise we would have a tonne of unnecessary re-rendering going on or poor scroll matching
    useEffect(() => {
        if (listRef.current) {
            if (document.getElementById('PlayerInspectorListMarker')) {
                return
            }
            const listElement = document.getElementById('PlayerInspectorList')
            const positionMarkerEl = document.createElement('div')
            positionMarkerEl.id = 'PlayerInspectorListMarker'
            listElement?.appendChild(positionMarkerEl)
        }
    }, [listRef.current])

    useEffect(() => {
        if (listRef.current) {
            const offset = range(playbackIndicatorIndexStop).reduce(
                (acc, x) => acc + cellMeasurerCache.getHeight(x, 0),
                0
            )
            document
                .getElementById('PlayerInspectorListMarker')
                ?.setAttribute('style', `transform: translateY(${offset}px)`)

            if (!syncScrollingPaused && syncScroll) {
                scrolledByJsFlag.current = true
                listRef.current.scrollToRow(playbackIndicatorIndex)
            }
        }
    }, [playbackIndicatorIndex, syncScroll])

    const renderRow: ListRowRenderer = ({ index, key, parent, style }) => {
        return (
            <CellMeasurer cache={cellMeasurerCache} columnIndex={0} key={key} rowIndex={index} parent={parent}>
                {({ measure, registerChild }) => (
                    // eslint-disable-next-line react/forbid-dom-props
                    <div ref={(r) => registerChild?.(r || undefined)} style={style}>
                        <PlayerInspectorListItem
                            key={index}
                            item={items[index]}
                            index={index}
                            onLayout={({ height }) => {
                                // Optimization to ensure that we only call measure if the dimensions have actually changed
                                if (height !== cellMeasurerCache.getHeight(index, 0)) {
                                    measure()
                                }
                            }}
                        />
                    </div>
                )}
            </CellMeasurer>
        )
    }

    return (
        <div className="flex flex-col bg-side flex-1 overflow-hidden relative">
            {!fullLoad ? (
                <div className="p-16 text-center text-muted-alt">Data will be shown once playback starts</div>
            ) : items.length ? (
                <div
                    className="absolute inset-0"
                    onMouseEnter={() => (mouseHoverRef.current = true)}
                    onMouseLeave={() => (mouseHoverRef.current = false)}
                >
                    <AutoSizer>
                        {({ height, width }) => (
                            <List
                                className="p-2"
                                height={height}
                                width={width}
                                deferredMeasurementCache={cellMeasurerCache}
                                overscanRowCount={20}
                                rowCount={items.length}
                                rowHeight={cellMeasurerCache.rowHeight}
                                rowRenderer={renderRow}
                                ref={listRef as any}
                                id="PlayerInspectorList"
                                onScroll={() => {
                                    // TRICKY: There is no way to know for sure whether the scroll is directly from user input
                                    // As such we only pause scrolling if we the last scroll triggered wasn't by the auto-scroller
                                    // and the user is currently hovering over the list
                                    if (!scrolledByJsFlag.current && mouseHoverRef.current) {
                                        setSyncScrollPaused(true)
                                    }
                                    scrolledByJsFlag.current = false
                                }}
                            />
                        )}
                    </AutoSizer>
                </div>
            ) : tabsState[tab] === 'loading' ? (
                <div className="p-2">
                    <LemonSkeleton className="my-1 h-8" repeat={20} fade />
                </div>
            ) : tabsState[tab] === 'ready' ? (
                // If we are "ready" but with no results this must mean some results are filtered out
                <div className="p-16 text-center text-muted-alt">No results matching your filters.</div>
            ) : (
                <div className="p-16 text-center text-muted-alt">
                    {tab === SessionRecordingPlayerTab.CONSOLE ? (
                        <EmptyConsoleTab captureConsoleLogOptIn={currentTeam?.capture_console_log_opt_in || false} />
                    ) : tab === SessionRecordingPlayerTab.NETWORK ? (
                        <EmptyNetworkTab
                            captureNetworkFeatureAvailable={performanceAvailable}
                            captureNetworkLogOptIn={performanceEnabled}
                        />
                    ) : (
                        'No results found in this recording.'
                    )}
                </div>
            )}
        </div>
    )
}
