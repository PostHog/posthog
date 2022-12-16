import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { UnverifiedEvent, IconTerminal, IconGauge } from 'lib/components/icons'
import { colonDelimitedDuration } from 'lib/utils'
import { useCallback, useEffect, useMemo } from 'react'
import { List, ListRowRenderer } from 'react-virtualized/dist/es/List'
import { CellMeasurer, CellMeasurerCache } from 'react-virtualized/dist/es/CellMeasurer'
import { SessionRecordingPlayerTab } from '~/types'
import { SessionRecordingPlayerLogicProps } from '../../sessionRecordingPlayerLogic'
import { SharedListItem, sharedListLogic } from '../sharedListLogic'
import { ItemConsoleLog } from './components/ItemConsoleLog'
import { ItemEvent } from './components/ItemEvent'
import { ItemPerformanceEvent } from './components/ItemPerformanceEvent'
import AutoSizer from 'react-virtualized/dist/es/AutoSizer'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { useDebouncedCallback } from 'use-debounce'

const TabToIcon = {
    [SessionRecordingPlayerTab.EVENTS]: <UnverifiedEvent />,
    [SessionRecordingPlayerTab.CONSOLE]: <IconTerminal />,
    [SessionRecordingPlayerTab.PERFORMANCE]: <IconGauge />,
}

function PlayerInspectorListItem({
    item,
    index,
    logicProps,
    onLayout,
}: {
    item: SharedListItem
    index: number
    logicProps: SessionRecordingPlayerLogicProps
    onLayout: () => void
}): JSX.Element {
    const { tab, lastItemTimestamp, recordingTimeInfo, expandedItems, timestampMode } = useValues(
        sharedListLogic(logicProps)
    )
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
    // Height changes should layout immediately but width ones (browser resize can be much slower)
    useEffect(() => onLayoutDebounced(), [width])
    useEffect(() => onLayout(), [height])

    return (
        <div ref={ref} className={clsx('flex flex-1 overflow-hidden gap-2', index > 0 && 'mt-1')}>
            {showIcon ? (
                <span className="shrink-0 text-lg text-muted-alt h-8 w-5 text-center flex items-center justify-center">
                    {TabToIcon[item.type]}
                </span>
            ) : null}
            <span className="flex-1 overflow-hidden">
                {item.type === 'performance' ? (
                    <ItemPerformanceEvent item={item.data} finalTimestamp={lastItemTimestamp} {...itemProps} />
                ) : item.type === 'console' ? (
                    <ItemConsoleLog item={item} />
                ) : item.type === 'events' ? (
                    <ItemEvent item={item} />
                ) : null}
            </span>
            <span className="shrink-0 text-muted-alt mt-2 text-center text-xs cursor-pointer">
                {timestampMode === 'absolute' ? (
                    <>{item.timestamp.format('DD MMM HH:mm:ss')}</>
                ) : (
                    <>
                        {item.timeInRecording < 0
                            ? 'LOAD'
                            : colonDelimitedDuration(item.timeInRecording / 1000, fixedUnits)}
                    </>
                )}
            </span>
        </div>
    )
}

export function PlayerInspectorList(props: SessionRecordingPlayerLogicProps): JSX.Element {
    const { items } = useValues(sharedListLogic(props))

    const cellMeasurerCache = useMemo(
        () =>
            new CellMeasurerCache({
                fixedWidth: true,
                minHeight: 10,
            }),
        [items]
    )

    const renderRow: ListRowRenderer = useCallback(
        ({ index, key, parent, style }) => {
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
                                onLayout={measure}
                            />
                        </div>
                    )}
                </CellMeasurer>
            )
        },
        [items]
    )

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
                                overscanRowCount={10}
                                rowCount={items.length}
                                rowHeight={cellMeasurerCache.rowHeight}
                                rowRenderer={renderRow}
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
