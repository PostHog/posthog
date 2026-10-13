import { useValues } from 'kea'

import { Link } from 'lib/lemon-ui/Link'
import { DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'
import { urls } from 'scenes/urls'

import { lineageDataLogic } from 'products/data_modeling/frontend/lineage/lineageDataLogic'

import { LineageTarget, findLineageNode } from './findLineageNode'

export function SeeLineageMenuItem({ target }: { target: LineageTarget }): JSX.Element {
    const { nodes, nodesLoading } = useValues(lineageDataLogic)
    const node = findLineageNode(nodes, target)

    return (
        <DropdownMenuItem asChild>
            <Link
                to={node ? urls.nodeDetail(node.id, 'lineage') : undefined}
                onClick={(e) => e.stopPropagation()}
                disabledReason={node ? undefined : nodesLoading ? 'Loading lineage' : 'Lineage is not available'}
                buttonProps={{ menuItem: true }}
                data-attr="sql-editor-sidebar-see-lineage"
            >
                See lineage
            </Link>
        </DropdownMenuItem>
    )
}
