import { useValues } from 'kea'
import { useRef } from 'react'

import { databaseTablePreviewLogic } from './databaseTablePreviewLogic'
import type { DatabaseTablePreviewLogicProps } from './databaseTablePreviewLogic'
import { TablePreview, TablePreviewProps } from './TablePreview'
import { TablePreviewExpressionColumn } from './types'

export interface DatabaseTablePreviewProps extends Omit<TablePreviewProps, 'loading' | 'previewData' | 'extraColumns'> {
    logicKey?: string
    limit?: number
    whereClause?: string | null
    expressionColumns?: TablePreviewExpressionColumn[]
    queryFilters?: DatabaseTablePreviewLogicProps['queryFilters']
    queryModifiers?: DatabaseTablePreviewLogicProps['queryModifiers']
}

let uniqueMemoizedIndex = 0

export function DatabaseTablePreview({
    table,
    logicKey,
    limit,
    whereClause,
    expressionColumns,
    queryFilters,
    queryModifiers,
    ...rest
}: DatabaseTablePreviewProps): JSX.Element {
    const instanceLogicKey = useRef(logicKey || `database-table-preview-${uniqueMemoizedIndex++}`).current

    const logic = databaseTablePreviewLogic({
        logicKey: instanceLogicKey,
        tableName: table?.name,
        limit,
        whereClause,
        expressionColumns,
        queryFilters,
        queryModifiers,
    })
    const { previewData, previewDataLoading } = useValues(logic)

    return (
        <TablePreview
            table={table}
            previewData={previewData}
            loading={previewDataLoading}
            extraColumns={expressionColumns}
            {...rest}
        />
    )
}
