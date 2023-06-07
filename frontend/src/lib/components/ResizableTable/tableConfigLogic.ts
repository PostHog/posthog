import { kea } from 'kea'
import type { tableConfigLogicType } from './tableConfigLogicType'
import { ColumnChoice } from '~/types'
import { HOGQL_COLUMNS_KEY } from '~/queries/nodes/DataTable/defaultEventsQuery'

export interface TableConfigLogicProps {
    startingColumns?: ColumnChoice
}

/** Returns null if saved columns are of the new HogQL type */
function filterV2Columns(
    startingColumns: string[] | null | undefined | 'DEFAULT'
): string[] | null | undefined | 'DEFAULT' {
    if (Array.isArray(startingColumns) && startingColumns[0] === HOGQL_COLUMNS_KEY) {
        return null
    }
    return startingColumns
}

export const tableConfigLogic = kea<tableConfigLogicType>({
    path: ['lib', 'components', 'ResizableTable', 'tableConfigLogic'],
    props: { startingColumns: 'DEFAULT' } as TableConfigLogicProps,
    actions: {
        showModal: true,
        hideModal: true,
        setSelectedColumns: (columnConfig: ColumnChoice) => ({ columnConfig }),
    },
    reducers: ({ props }) => ({
        selectedColumns: [
            (filterV2Columns(props.startingColumns) || 'DEFAULT') as ColumnChoice,
            {
                setSelectedColumns: (_, { columnConfig }) => columnConfig,
            },
        ],
        modalVisible: [
            false,
            {
                showModal: () => true,
                hideModal: () => false,
                setSelectedColumns: () => false,
            },
        ],
    }),
    selectors: {
        tableWidth: [
            (selectors) => [selectors.selectedColumns],
            (selectedColumns: ColumnChoice): number => {
                return selectedColumns === 'DEFAULT' ? 7 : selectedColumns.length + 2 // Time and Actions columns are appended by default at the end of the columns (thus the `+ 2`)
            },
        ],
    },
})
