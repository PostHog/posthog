import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { UnverifiedEvent, IconTerminal, IconGauge } from 'lib/components/icons'
import { colonDelimitedDuration, disableHourFor } from 'lib/utils'
import { useEffect, useMemo, useRef } from 'react'
import { List, ListRowRenderer } from 'react-virtualized/dist/es/List'
import { CellMeasurer, CellMeasurerCache } from 'react-virtualized/dist/es/CellMeasurer'
import { SessionRecordingPlayerTab } from '~/types'
import { sessionRecordingPlayerLogic, SessionRecordingPlayerLogicProps } from '../../sessionRecordingPlayerLogic'
import { SharedListItem, sharedListLogic } from '../sharedListLogic'
import { ItemConsoleLog } from './components/ItemConsoleLog'
import { ItemEvent } from './components/ItemEvent'
import { ItemPerformanceEvent } from './components/ItemPerformanceEvent'
import AutoSizer from 'react-virtualized/dist/es/AutoSizer'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { useDebouncedCallback } from 'use-debounce'
import { LemonButton } from '@posthog/lemon-ui'
import { Tooltip } from 'lib/components/Tooltip'
import './PlayerInspectorList.scss'

const TabToIcon = {
    [SessionRecordingPlayerTab.EVENTS]: <UnverifiedEvent />,
    [SessionRecordingPlayerTab.CONSOLE]: <IconTerminal />,
    [SessionRecordingPlayerTab.PERFORMANCE]: <IconGauge />,
}

const PLAYER_INSPECTOR_LIST_ITEM_MARGIN_TOP = 4

function PlayerInspectorListItem({
    item,
    index,
    logicProps,
    onLayout,
}: {
    item: SharedListItem
    index: number
    logicProps: SessionRecordingPlayerLogicProps
    onLayout: (layout: { width: number; height: number }) => void
}): JSX.Element {
    const { tab, lastItemTimestamp, recordingTimeInfo, expandedItems, timestampMode, playerPosition } = useValues(
        sharedListLogic(logicProps)
    )
    const { seekToTime } = useActions(sessionRecordingPlayerLogic(logicProps))
    const { setItemExpanded } = useActions(sharedListLogic(logicProps))
    const showIcon = tab === SessionRecordingPlayerTab.ALL
    const fixedUnits = recordingTimeInfo.duration / 1000 > 3600 ? 3 : 2

    const isExpanded = expandedItems.includes(index)

    const itemProps = {
        setExpanded: () => setItemExpanded(index, !isExpanded),
        expanded: isExpanded,
    }

    const onLayoutDebounced = useDebouncedCallback(onLayout, 500)
    const { ref, width, height } = useResizeObserver({})

    const totalHeight = height && index > 0 ? height + PLAYER_INSPECTOR_LIST_ITEM_MARGIN_TOP : height

    console.log('RENDER', index, playerPosition)

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

    return (
        <div
            ref={ref}
            className={clsx('flex flex-1 overflow-hidden gap-2 relative')}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                marginTop: index > 0 ? PLAYER_INSPECTOR_LIST_ITEM_MARGIN_TOP : undefined, // Style as we need it for the layout optimisation
            }}
        >
            {!isExpanded && showIcon ? (
                <span className="shrink-0 text-lg text-muted-alt h-8 w-5 text-center flex items-center justify-center">
                    {TabToIcon[item.type]}
                </span>
            ) : null}

            {playerPosition.markerPosition === index ? (
                <span className="absolute right-0 top-0 bg-primary-light rounded p-2">HERE!</span>
            ) : null}

            <span
                className={clsx(
                    'flex-1 overflow-hidden rounded border',
                    isExpanded && 'border-primary',
                    item.highlightColor && `border-${item.highlightColor}-dark bg-${item.highlightColor}-highlight`,
                    !item.highlightColor && 'bg-light'
                )}
            >
                {item.type === 'performance' ? (
                    <ItemPerformanceEvent item={item.data} finalTimestamp={lastItemTimestamp} {...itemProps} />
                ) : item.type === 'console' ? (
                    <ItemConsoleLog item={item} {...itemProps} />
                ) : item.type === 'events' ? (
                    <ItemEvent item={item} {...itemProps} />
                ) : null}
            </span>
            {!isExpanded && (
                <LemonButton
                    size="small"
                    noPadding
                    status="primary-alt"
                    onClick={() => {
                        // NOTE: We offset by 1 second so that the playback startsjust before the event occurs
                        seekToTime(item.timeInRecording - 1000)
                    }}
                >
                    <span className="p-1 text-xs">
                        {timestampMode === 'absolute' ? (
                            <>{item.timestamp.format('DD MMM HH:mm:ss')}</>
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

export function PlayerInspectorList(props: SessionRecordingPlayerLogicProps): JSX.Element {
    const { items, playerPosition } = useValues(sharedListLogic(props))

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

    // TRICKY: this is hacky but there is no other way to add a timestamp marker to the <List> component children
    // We want this as otherwise we would have a tonne of unecessary re-rendering going on or poor scroll matching
    useEffect(() => {
        if (listRef.current) {
            const listElement = document.getElementById('PlayerInspectorList')
            const positionMarkerEl = document.createElement('div')
            positionMarkerEl.id = 'PlayerInspectorListMarker'
            listElement?.appendChild(positionMarkerEl)
        }
    }, [listRef.current])

    useEffect(() => {
        if (listRef.current) {
            const markerTopPos = listRef.current?.getOffsetForRow({
                alignment: 'start',
                index: playerPosition.markerPosition,
            })
            console.log({ markerTopPos })
            document.getElementById('PlayerInspectorListMarker')?.setAttribute('style', `top: ${markerTopPos}px`)
        }
    }, [playerPosition.markerPosition])

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
                            logicProps={props}
                            onLayout={({ height }) => {
                                // Optimization to ensure that we only call measure if the dimensions have actually changed
                                if (height !== cellMeasurerCache.getHeight(index, 0)) {
                                    console.log('LAyout!!', cellMeasurerCache.getHeight(index, 0), height)
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
            {items.length ? (
                <div className="absolute inset-0">
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
                                ref={listRef}
                                id="PlayerInspectorList"
                            />
                        )}
                    </AutoSizer>
                </div>
            ) : (
                <div className="flex-1 flex items-center justify-center text-muted-alt">No results</div>
            )}
        </div>
    )
}
