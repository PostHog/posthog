import './PlayerInspectorList.scss'

import { range } from 'd3'
import { useActions, useValues } from 'kea'
import { CSSProperties, useCallback, useEffect, useRef } from 'react'
import { List, useDynamicRowHeight, useListRef } from 'react-window'

import { AutoSizer } from 'lib/components/AutoSizer'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerInspectorListItem } from './components/PlayerInspectorListItem'
import { InspectorListItem, playerInspectorLogic } from './playerInspectorLogic'

export const DEFAULT_INSPECTOR_ROW_HEIGHT = 40

interface InspectorRowProps {
    items: InspectorListItem[]
    dynamicRowHeight: ReturnType<typeof useDynamicRowHeight>
}

function InspectorRow({
    index,
    style,
    items,
    dynamicRowHeight,
}: {
    ariaAttributes: Record<string, unknown>
    index: number
    style: CSSProperties
} & InspectorRowProps): JSX.Element {
    const rowRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (rowRef.current) {
            return dynamicRowHeight.observeRowElements([rowRef.current])
        }
    }, [dynamicRowHeight])

    return (
        <div ref={rowRef} style={style} data-index={index}>
            <PlayerInspectorListItem key={index} item={items[index]} index={index} />
        </div>
    )
}

export function PlayerInspectorList(): JSX.Element {
    const { logicProps, snapshotsLoaded } = useValues(sessionRecordingPlayerLogic)
    const inspectorLogic = playerInspectorLogic(logicProps)

    const { items, isLoading, isReady, playbackIndicatorIndex, playbackIndicatorIndexStop, syncScrollPaused } =
        useValues(inspectorLogic)
    const { setSyncScrollPaused } = useActions(inspectorLogic)

    const dynamicRowHeight = useDynamicRowHeight({ defaultRowHeight: DEFAULT_INSPECTOR_ROW_HEIGHT })

    const listRef = useListRef(null)
    const markerRef = useRef<HTMLDivElement>(null)
    const scrolledByJsFlag = useRef<boolean>(true)
    const mouseHoverRef = useRef<boolean>(false)

    useEffect(() => {
        if (listRef.current && markerRef.current) {
            const offset = range(playbackIndicatorIndexStop).reduce(
                (acc, x) => acc + (dynamicRowHeight.getRowHeight(x) ?? DEFAULT_INSPECTOR_ROW_HEIGHT),
                0
            )
            markerRef.current.style.transform = `translateY(${offset}px)`

            if (!syncScrollPaused && playbackIndicatorIndex >= 0) {
                scrolledByJsFlag.current = true
                listRef.current.scrollToRow({ index: playbackIndicatorIndex })
            }
        }
    }, [playbackIndicatorIndex]) // oxlint-disable-line react-hooks/exhaustive-deps

    const handleScroll = useCallback(() => {
        // TRICKY: There is no way to know for sure whether the scroll is directly from user input
        // As such we only pause scrolling if we the last scroll triggered wasn't by the auto-scroller
        // and the user is currently hovering over the list
        if (!scrolledByJsFlag.current && mouseHoverRef.current) {
            setSyncScrollPaused(true)
        }
        scrolledByJsFlag.current = false
    }, [setSyncScrollPaused])

    return (
        <div className="flex flex-col bg-primary flex-1 overflow-hidden relative">
            {!snapshotsLoaded ? (
                <div className="p-16 text-center text-secondary">Data will be shown once playback starts</div>
            ) : items.length ? (
                <div
                    className="absolute inset-0"
                    onMouseEnter={() => (mouseHoverRef.current = true)}
                    onMouseLeave={() => (mouseHoverRef.current = false)}
                >
                    <AutoSizer
                        renderProp={({ height, width }) =>
                            height && width ? (
                                <List<InspectorRowProps>
                                    style={{ height, width }}
                                    overscanCount={20}
                                    rowCount={items.length}
                                    rowHeight={dynamicRowHeight}
                                    rowComponent={InspectorRow}
                                    rowProps={{ items, dynamicRowHeight }}
                                    listRef={listRef}
                                    id="PlayerInspectorList"
                                    onScroll={handleScroll}
                                >
                                    <div ref={markerRef} id="PlayerInspectorListMarker" />
                                </List>
                            ) : null
                        }
                    />
                </div>
            ) : isLoading ? (
                <div className="p-2">
                    <LemonSkeleton className="my-1 h-8" repeat={20} fade />
                </div>
            ) : isReady ? (
                // If we are "ready" but with no results this must mean some results are filtered out
                <div className="p-16 text-center text-secondary">No results matching your filters.</div>
            ) : null}
        </div>
    )
}
