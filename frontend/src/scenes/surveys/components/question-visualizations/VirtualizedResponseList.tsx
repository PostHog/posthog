import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { Grid, GridCellProps } from 'react-virtualized/dist/es/Grid'

import { TZLabel } from 'lib/components/TZLabel'
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

    return (
        <div className="border rounded bg-surface-primary p-2 h-full flex flex-col">
            <div className="text-sm flex-1 line-clamp-2 mb-1">{responseText}</div>
            <div className="flex items-center justify-between text-xs text-muted">
                <PersonDisplay
                    person={{
                        distinct_id: response.distinctId,
                        properties: response.personProperties || {},
                    }}
                    withIcon="xs"
                    noEllipsis={false}
                />
                {response.timestamp && <TZLabel time={response.timestamp} formatDate="MMM D" formatTime="HH:mm" />}
            </div>
        </div>
    )
}

export function VirtualizedResponseList({ responses, maxHeight = 400 }: VirtualizedResponseListProps): JSX.Element {
    const rowCount = Math.ceil(responses.length / COLUMN_COUNT)

    const cellRenderer = ({ columnIndex, rowIndex, key, style }: GridCellProps): JSX.Element | null => {
        const index = rowIndex * COLUMN_COUNT + columnIndex
        if (index >= responses.length) {
            return null
        }
        const response = responses[index]

        // Add gap between columns
        const adjustedStyle = {
            ...style,
            left: Number(style.left) + columnIndex * COLUMN_GAP,
            width: Number(style.width) - COLUMN_GAP,
            paddingBottom: 8,
        }

        return (
            <div key={key} style={adjustedStyle}>
                <ResponseListItem response={response} />
            </div>
        )
    }

    // For small lists, render without virtualization
    if (responses.length <= 8) {
        return (
            <div className="grid grid-cols-2 gap-2">
                {responses.map((response, index) => (
                    <ResponseListItem key={`${response.distinctId}-${index}`} response={response} />
                ))}
            </div>
        )
    }

    return (
        <div style={{ height: Math.min(rowCount * ROW_HEIGHT, maxHeight) }}>
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
                    />
                )}
            </AutoSizer>
        </div>
    )
}
