import { useValues } from 'kea'
import { useMemo } from 'react'

import { TablePreview, TablePreviewProps } from './TablePreview'
import { databaseTablePreviewLogic } from './databaseTablePreviewLogic'

export interface DatabaseTablePreviewProps extends Omit<TablePreviewProps, 'loading' | 'previewData'> {
    logicKey?: string
    limit?: number
    whereClause?: string | null
}

let uniqueMemoizedIndex = 0

export function DatabaseTablePreview({
    table,
    logicKey,
    limit,
    whereClause,
    ...rest
}: DatabaseTablePreviewProps): JSX.Element {
const instanceLogicKey = useRef(logicKey || `database-table-preview-${uniqueMemoizedIndex++}`).current

    const logic = databaseTablePreviewLogic({
        logicKey: instanceLogicKey,
        tableName: table?.name,
        limit,
        whereClause,
    })
    const { previewData, previewDataLoading } = useValues(logic)

    return <TablePreview table={table} previewData={previewData} loading={previewDataLoading} {...rest} />
}
