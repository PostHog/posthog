import './PlayerInspectorList.scss'

import { range } from 'd3'
import { useActions, useValues } from 'kea'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { useEffect, useMemo, useRef } from 'react'
import AutoSizer from 'react-virtualized/dist/es/AutoSizer'
import { CellMeasurer, CellMeasurerCache } from 'react-virtualized/dist/es/CellMeasurer'
import { List, ListRowRenderer } from 'react-virtualized/dist/es/List'

import { FilterableInspectorListItemTypes } from '~/types'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerInspectorListItem } from './components/PlayerInspectorListItem'
import { playerInspectorLogic } from './playerInspectorLogic'

export const DEFAULT_INSPECTOR_ROW_HEIGHT = 40

export function PlayerInspectorList(): JSX.Element {
    const { logicProps, snapshotsLoaded } = useValues(sessionRecordingPlayerLogic)
    const inspectorLogic = playerInspectorLogic(logicProps)

    const { items, inspectorDataState, playbackIndicatorIndex, playbackIndicatorIndexStop, syncScrollPaused } =
        useValues(inspectorLogic)
    const { setSyncScrollPaused } = useActions(inspectorLogic)

    const cellMeasurerCache = useMemo(
        () =>
            new CellMeasurerCache({
                fixedWidth: true,
                minHeight: 10,
                defaultHeight: DEFAULT_INSPECTOR_ROW_HEIGHT,
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

            if (!syncScrollPaused) {
                scrolledByJsFlag.current = true
                listRef.current.scrollToRow(playbackIndicatorIndex)
            }
        }
    }, [playbackIndicatorIndex])

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
        <div className="flex flex-col bg-bg-3000 flex-1 overflow-hidden relative">
            {!snapshotsLoaded ? (
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
            ) : inspectorDataState[FilterableInspectorListItemTypes.EVENTS] === 'loading' ||
              inspectorDataState[FilterableInspectorListItemTypes.CONSOLE] === 'loading' ||
              inspectorDataState[FilterableInspectorListItemTypes.NETWORK] === 'loading' ? (
                <div className="p-2">
                    <LemonSkeleton className="my-1 h-8" repeat={20} fade />
                </div>
            ) : inspectorDataState[FilterableInspectorListItemTypes.EVENTS] === 'ready' ||
              inspectorDataState[FilterableInspectorListItemTypes.CONSOLE] === 'ready' ||
              inspectorDataState[FilterableInspectorListItemTypes.NETWORK] === 'ready' ? (
                // If we are "ready" but with no results this must mean some results are filtered out
                <div className="p-16 text-center text-muted-alt">No results matching your filters.</div>
            ) : null}
        </div>
    )
}
