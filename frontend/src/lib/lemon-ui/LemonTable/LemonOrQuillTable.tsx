import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { LemonTable, LemonTableProps } from './LemonTable'
import { QuillLemonTable } from './QuillLemonTable'
import { LemonTableColumnGroup } from './types'
import { BulkSelectionKey } from './useBulkSelection'

/** Features the quill table has no equivalent for yet. A table that uses one stays on LemonTable. */
function canRenderWithQuill<T extends Record<string, any>, K extends BulkSelectionKey>(
    props: LemonTableProps<T, K>
): boolean {
    if (props.bulkSelection || props.virtualized || props.headerRows?.length || props.pinnedColumns?.length) {
        return false
    }
    if (props.enableCellCopy) {
        return false
    }
    const columns =
        props.columns.length > 0 && 'children' in props.columns[0]
            ? (props.columns as LemonTableColumnGroup<T>[]).flatMap((group) => group.children)
            : (props.columns as LemonTableColumnGroup<T>['children'])
    return !columns.some((column) => column.resizable || column.cellActions || column.more)
}

/** Renders the quill `DataTable` behind `today-rail-nav` and LemonTable otherwise. */
export function LemonOrQuillTable<T extends Record<string, any>, K extends BulkSelectionKey = BulkSelectionKey>(
    props: LemonTableProps<T, K>
): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    return todayRailNav && canRenderWithQuill(props) ? <QuillLemonTable {...props} /> : <LemonTable {...props} />
}
