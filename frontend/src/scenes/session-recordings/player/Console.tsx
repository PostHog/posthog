import { useActions, useValues } from 'kea'
import React from 'react'
import { sessionRecordingLogic } from '../sessionRecordingLogic'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'
import './Console.scss'
import { eventWithTime } from 'rrweb/typings/types'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import List, { ListRowProps } from 'react-virtualized/dist/es/List'

export function Console(): JSX.Element | null {
    const { sessionPlayerData } = useValues(sessionRecordingLogic)
    const { currentPlayerPosition } = useValues(sessionRecordingPlayerLogic)
    const { seek } = useActions(sessionRecordingPlayerLogic)
    if (!currentPlayerPosition?.windowId || !sessionPlayerData) {
        return <>No logs found for this recording.</>
    }
    const logs = sessionPlayerData.snapshotsByWindowId[currentPlayerPosition?.windowId || '']?.filter(
        (item: eventWithTime) => item.type === 6
    )
    if (!logs || logs.length === 0) {
        return <>No logs found for this recording.</>
    }

    // const rowRenderer = useCallback(
    const rowRenderer = ({ index, style, key }: ListRowProps): JSX.Element => {
        const log = logs[index]
        const { level, payload, trace } = log.data.payload

        let splitTrace
        try {
            splitTrace = [...trace[0].matchAll(/(.*):([0-9]+):[0-9]+/g)][0]
        } catch (e) {}
        let path = ''
        try {
            path = new URL(splitTrace[1]).pathname.split('/').slice(-1)[0]
        } catch (e) {}

        return (
            <div
                className={`log-line level-${level}`}
                style={{ ...style }}
                key={key}
                onClick={() => {
                    seek({
                        time:
                            log.timestamp -
                            sessionPlayerData.metadata.startAndEndTimesByWindowId[currentPlayerPosition.windowId]
                                .startTimeEpochMs -
                            1000,
                        windowId: currentPlayerPosition.windowId,
                    })
                }}
            >
                <div>
                    {payload
                        .map((item: string) => (item.startsWith('"') && item.endsWith('"') ? item.slice(1, -1) : item))
                        .join(' ')}
                </div>
                <a href={splitTrace[1]} target="_blank">
                    {path}:{splitTrace[2]}
                </a>
                <br />
            </div>
        )
    }

    return (
        <div className="console-log">
            <AutoSizer>
                {({ height, width }: { height: number; width: number }) => {
                    return (
                        <List
                            // ref={listRef}
                            className="event-list-virtual"
                            height={height}
                            width={width}
                            // onRowsRendered={setRenderedRows}
                            // noRowsRenderer={noRowsRenderer}
                            // cellRangeRenderer={cellRangeRenderer}
                            // overscanRowCount={OVERSCANNED_ROW_COUNT} // in case autoscrolling scrolls faster than we render.
                            // overscanIndicesGetter={overscanIndicesGetter}
                            rowCount={logs.length}
                            rowRenderer={rowRenderer}
                            rowHeight={21}
                        />
                    )
                }}
            </AutoSizer>
        </div>
    )
}
