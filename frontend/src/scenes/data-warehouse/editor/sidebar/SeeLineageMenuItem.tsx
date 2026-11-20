import { combineUrl } from 'kea-router'

import { Link } from 'lib/lemon-ui/Link'
import { ContextMenuItem } from 'lib/ui/ContextMenu/ContextMenu'
import { DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'
import { urls } from 'scenes/urls'

import type { DataModelingNodesRetrieveLookup } from 'products/data_modeling/frontend/generated/api.schemas'

export interface LineageTarget {
    id: string
    lookup: DataModelingNodesRetrieveLookup
}

export function SeeLineageMenuItem({
    target,
    MenuItem = DropdownMenuItem,
}: {
    target: LineageTarget
    MenuItem?: typeof ContextMenuItem | typeof DropdownMenuItem
}): JSX.Element {
    return (
        <MenuItem asChild>
            <Link
                to={combineUrl(urls.nodeDetail(target.id, 'lineage'), { lookup: target.lookup }).url}
                onClick={(e) => e.stopPropagation()}
                buttonProps={{ menuItem: true }}
                data-attr="sql-editor-sidebar-see-lineage"
            >
                See lineage
            </Link>
        </MenuItem>
    )
}
