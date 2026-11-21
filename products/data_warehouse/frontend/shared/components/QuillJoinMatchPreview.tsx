import { useValues } from 'kea'

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Text } from '@posthog/quill'

import { viewLinkLogic } from '../logics/viewLinkLogic'

const COLUMN_TITLES: Record<string, string> = {
    source_key: 'Source key',
    joining_key: 'Joining key',
}

export function QuillJoinMatchPreview(): JSX.Element | null {
    const { joinValidation } = useValues(viewLinkLogic)
    const response = joinValidation.response

    if (joinValidation.status !== 'valid' || !response) {
        return null
    }

    const columns = response.columns ?? []

    return (
        <div className="flex flex-col gap-2">
            {response.match_rate != null && response.total_rows != null && (
                <Text size="xs" variant="muted" render={<span className="m-0" />}>
                    {`${Math.round(response.match_rate * 100)}% of ${response.total_rows.toLocaleString()} sampled rows matched`}
                </Text>
            )}
            {columns.length > 0 && response.results.length > 0 && (
                <Table>
                    <TableHeader>
                        <TableRow>
                            {columns.map((column) => (
                                <TableHead key={column}>{COLUMN_TITLES[column] ?? column}</TableHead>
                            ))}
                        </TableRow>
                    </TableHeader>
                    <TableBody translate="no">
                        {response.results.map((row: any[], rowIndex: number) => (
                            <TableRow key={rowIndex}>
                                {columns.map((column, columnIndex) => (
                                    <TableCell key={column} className="font-mono">
                                        {String(row[columnIndex] ?? '')}
                                    </TableCell>
                                ))}
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            )}
        </div>
    )
}
