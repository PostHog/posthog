import { More } from 'lib/lemon-ui/LemonButton/More'

import { DataTableNode } from '~/queries/schema/schema-general'
import { CellActionProps, QueryContext } from '~/queries/types'

interface CellActionsProps {
    columnName: string
    query: DataTableNode
    record: unknown
    recordIndex: number
    value: unknown
    context?: QueryContext<DataTableNode>
    children: React.ReactNode
}

export function CellActions({
    columnName,
    query,
    record,
    recordIndex,
    value,
    context,
    children,
}: CellActionsProps): JSX.Element {
    const cellActionsRenderer = context?.columns?.[columnName]?.cellActions

    if (!cellActionsRenderer) {
        return <>{children}</>
    }

    const actionProps: CellActionProps = {
        columnName,
        query,
        record,
        recordIndex,
        value,
    }

    const actions = cellActionsRenderer(actionProps)

    if (!actions) {
        return <>{children}</>
    }

    return (
        <div className="flex items-center gap-1">
            <div className="flex-1 min-w-0">{children}</div>
            <div className="flex-shrink-0">
                <More overlay={actions} size="xsmall" />
            </div>
        </div>
    )
}
