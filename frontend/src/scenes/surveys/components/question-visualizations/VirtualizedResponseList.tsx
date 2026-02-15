import { CSSProperties, useCallback, useState } from 'react'
import { Grid } from 'react-window'

import { AutoSizer } from 'lib/components/AutoSizer'
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
                    person={{ distinct_id: response.distinctId }}
                    displayName={response.personDisplayName}
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
                            person={{ distinct_id: response.distinctId }}
                            displayName={response.personDisplayName}
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

interface ResponseCellProps {
    responses: OpenQuestionResponseData[]
}

function ResponseCell({
    columnIndex,
    rowIndex,
    style,
    responses,
}: {
    ariaAttributes: Record<string, unknown>
    columnIndex: number
    rowIndex: number
    style: CSSProperties
} & ResponseCellProps): JSX.Element | null {
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
        <div style={adjustedStyle}>
            <ResponseListItem response={response} />
        </div>
    )
}

export function VirtualizedResponseList({ responses, maxHeight = 400 }: VirtualizedResponseListProps): JSX.Element {
    const rowCount = Math.ceil(responses.length / COLUMN_COUNT)
    const [isAtBottom, setIsAtBottom] = useState(false)

    const containerHeight = Math.min(rowCount * ROW_HEIGHT, maxHeight)
    const totalHeight = rowCount * ROW_HEIGHT
    const isScrollable = totalHeight > maxHeight

    const handleScroll = useCallback(
        (event: React.UIEvent<HTMLDivElement>): void => {
            const { scrollTop, clientHeight, scrollHeight } = event.currentTarget
            const atBottom = scrollTop + clientHeight >= scrollHeight - 20
            setIsAtBottom(atBottom)
        },
        [setIsAtBottom]
    )

    if (responses.length <= 8) {
        return (
            <div className="grid grid-cols-2 gap-2">
                {responses.map((response, index) => (
                    <ResponseListItem key={`${response.distinctId}-${index}`} response={response} />
                ))}
            </div>
        )
    }

    const showScrollIndicator = isScrollable && !isAtBottom

    return (
        <div className="relative">
            <div style={{ height: containerHeight }}>
                <AutoSizer
                    renderProp={({ height, width }) =>
                        height && width ? (
                            <Grid<ResponseCellProps>
                                style={{ width, height }}
                                columnCount={COLUMN_COUNT}
                                columnWidth={(width - COLUMN_GAP) / COLUMN_COUNT}
                                rowCount={rowCount}
                                rowHeight={ROW_HEIGHT}
                                cellComponent={ResponseCell}
                                cellProps={{ responses }}
                                overscanCount={3}
                                onScroll={handleScroll}
                            />
                        ) : null
                    }
                />
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
