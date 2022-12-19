import { kea } from 'kea'
import type { tableConfigLogicType } from './tableConfigLogicType'
import { ColumnChoice } from '~/types'

export interface TableConfigLogicProps {
    startingColumns?: ColumnChoice
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
            (props.startingColumns || 'DEFAULT') as ColumnChoice,
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
