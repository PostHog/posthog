import { useState } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { Grid, GridCellProps, ScrollParams } from 'react-virtualized/dist/es/Grid'

import { TZLabel } from 'lib/components/TZLabel'
import { Popover } from 'lib/lemon-ui/Popover'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { OpenQuestionResponseData } from '~/types'

interface VirtualizedResponseListProps {
    responses: OpenQuestionResponseData[]
    maxHeight?: number
}

const ROW_HEIGHT = 72
const COLUMN_COUNT = 2
const COLUMN_GAP = 8

function ResponseListItem({ response }: { response: OpenQuestionResponseData }): JSX.Element {
    const responseText = typeof response.response !== 'string' ? JSON.stringify(response.response) : response.response
    const isLongResponse = responseText.length > 100
    const [isExpanded, setIsExpanded] = useState(false)

    const cardContent = (
        <div
            className={`border rounded bg-surface-primary p-2 h-full flex flex-col ${isLongResponse ? 'cursor-pointer hover:border-primary' : ''}`}
            onClick={isLongResponse ? () => setIsExpanded(!isExpanded) : undefined}
        >
            <div className="text-sm truncate mb-auto">{responseText}</div>
            <div className="flex items-center justify-between text-xs text-secondary mt-1">
                <PersonDisplay
                    person={{
                        distinct_id: response.distinctId,
                        properties: response.personProperties || {},
                    }}
                    withIcon="xs"
                    noEllipsis={false}
                    noLink={!response.distinctId}
                    muted
                />
                {response.timestamp && <TZLabel time={response.timestamp} formatDate="MMM D" formatTime="HH:mm" />}
            </div>
        </div>
    )

    if (!isLongResponse) {
        return cardContent
    }

    return (
        <Popover
            visible={isExpanded}
            onClickOutside={() => setIsExpanded(false)}
            placement="bottom-start"
            padded={false}
            overlay={
                <div className="max-w-sm p-3">
                    <p className="text-sm whitespace-pre-wrap leading-relaxed">{responseText}</p>
                    <div className="flex items-center justify-between text-xs text-secondary mt-3 pt-2 border-t">
                        <PersonDisplay
                            person={{
                                distinct_id: response.distinctId,
                                properties: response.personProperties || {},
                            }}
                            withIcon
                            noEllipsis={false}
                            noLink={!response.distinctId}
                        />
                        {response.timestamp && <TZLabel time={response.timestamp} />}
                    </div>
                </div>
            }
        >
            {cardContent}
        </Popover>
    )
}

export function VirtualizedResponseList({ responses, maxHeight = 400 }: VirtualizedResponseListProps): JSX.Element {
    const rowCount = Math.ceil(responses.length / COLUMN_COUNT)
    const [isAtBottom, setIsAtBottom] = useState(false)

    const containerHeight = Math.min(rowCount * ROW_HEIGHT, maxHeight)
    const totalHeight = rowCount * ROW_HEIGHT
    const isScrollable = totalHeight > maxHeight

    const cellRenderer = ({ columnIndex, rowIndex, key, style }: GridCellProps): JSX.Element | null => {
        const index = rowIndex * COLUMN_COUNT + columnIndex
        if (index >= responses.length) {
            return null
        }
        const response = responses[index]

        const adjustedStyle = {
            ...style,
            left: Number(style.left) + (columnIndex === 1 ? COLUMN_GAP : 0),
            paddingBottom: 8,
        }

        return (
            <div key={key} style={adjustedStyle}>
                <ResponseListItem response={response} />
            </div>
        )
    }

    if (responses.length <= 8) {
        return (
            <div className="grid grid-cols-2 gap-2">
                {responses.map((response, index) => (
                    <ResponseListItem key={`${response.distinctId}-${index}`} response={response} />
                ))}
            </div>
        )
    }

    const handleScroll = ({ scrollTop, clientHeight, scrollHeight }: ScrollParams): void => {
        const atBottom = scrollTop + clientHeight >= scrollHeight - 20
        setIsAtBottom(atBottom)
    }

    const showScrollIndicator = isScrollable && !isAtBottom

    return (
        <div className="relative">
            <div style={{ height: containerHeight }}>
                <AutoSizer>
                    {({ height, width }) => (
                        <Grid
                            width={width}
                            height={height}
                            columnCount={COLUMN_COUNT}
                            columnWidth={(width - COLUMN_GAP) / COLUMN_COUNT}
                            rowCount={rowCount}
                            rowHeight={ROW_HEIGHT}
                            cellRenderer={cellRenderer}
                            overscanRowCount={3}
                            onScroll={handleScroll}
                        />
                    )}
                </AutoSizer>
            </div>
            <div
                className={`absolute bottom-0 left-0 right-0 h-16 bg-gradient-to-t from-bg-light to-transparent pointer-events-none flex items-end justify-center pb-2 transition-all duration-300 ${
                    showScrollIndicator ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-2'
                }`}
            >
                <span className="text-xs text-primary-alt font-medium bg-surface-primary border rounded-full px-3 py-1 shadow-sm pointer-events-auto">
                    ↓ Scroll for more
                </span>
            </div>
        </div>
    )
}
