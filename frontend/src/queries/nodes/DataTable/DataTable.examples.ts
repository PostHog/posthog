import { DataTableNode, NodeKind } from '~/queries/schema'

const NoColumns: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: { kind: NodeKind.EventsNode },
    columns: undefined,
}

export const examples = { NoColumns }
