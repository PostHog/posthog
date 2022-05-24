import type { columnConfiguratorLogicType } from './columnConfiguratorLogicType'
import { tableConfigLogic } from 'lib/components/ResizableTable/tableConfigLogic'
import { kea } from 'kea'

export interface ColumnConfiguratorLogicProps {
    selectedColumns: string[] // the columns the table is currently displaying
}

export const columnConfiguratorLogic = kea<columnConfiguratorLogicType>({
    path: ['lib', 'components', 'ResizableTable', 'columnConfiguratorLogic'],
    props: { selectedColumns: [] } as ColumnConfiguratorLogicProps,
    connect: [tableConfigLogic],
    actions: {
        selectColumn: (column: string) => ({ column }),
        unselectColumn: (column: string) => ({ column }),
        resetColumns: (columns: string[]) => ({ columns }),
        save: true,
    },
    reducers: ({ props }) => ({
        selectedColumns: [
            props.selectedColumns,
            {
                selectColumn: (state, { column }) => Array.from(new Set([...state, column])),
                unselectColumn: (state, { column }) => state.filter((c) => c !== column),
                resetColumns: (_, { columns }) => columns,
            },
        ],
    }),
    listeners: ({ values }) => ({
        save: () => {
            tableConfigLogic.actions.setSelectedColumns(values.selectedColumns)
        },
    }),
})
