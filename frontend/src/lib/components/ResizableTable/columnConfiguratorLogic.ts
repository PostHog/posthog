import { kea } from 'kea'

export interface ColumnConfiguratorLogicProps {
    availableColumns: string[] // all of the columns the table could display
    selectedColumns: string[] //the columns the table is currently displaying
}

import { columnConfiguratorLogicType } from './columnConfiguratorLogicType'
import { tableConfigLogic } from 'lib/components/ResizableTable/tableConfigLogic'
import Fuse from 'fuse.js'

const filterColumns = (columnFilter: string, columns: string[]): string[] =>
    columnFilter
        ? new Fuse(columns, {
              threshold: 0.3,
          })
              .search(columnFilter)
              .map(({ item }) => item)
        : columns

export const columnConfiguratorLogic = kea<columnConfiguratorLogicType<ColumnConfiguratorLogicProps>>({
    props: { availableColumns: [], selectedColumns: [] } as ColumnConfiguratorLogicProps,
    actions: {
        selectColumn: (column: string) => ({ column }),
        unselectColumn: (column: string) => ({ column }),
        resetColumns: (columns: string[]) => ({ columns }),
        save: true,
        setColumnFilter: (searchTerm: string) => ({ searchTerm }),
    },
    reducers: ({ props }) => ({
        columnFilter: [
            '',
            {
                setColumnFilter: (_, { searchTerm }) => searchTerm,
            },
        ],
        visibleColumns: [
            props.selectedColumns,
            {
                selectColumn: (state, { column }) => [...state, column],
                unselectColumn: (state, { column }) => state.filter((c) => c !== column),
            },
        ],
        hiddenColumns: [
            props.availableColumns.filter((c) => !props.selectedColumns.includes(c)),
            {
                selectColumn: (state, { column }) => state.filter((c) => c !== column),
                unselectColumn: (state, { column }) => [...state, column],
            },
        ],
    }),
    selectors: {
        scrollIndex: [(selectors) => [selectors.visibleColumns], (visibleColumns) => visibleColumns.length],
        filteredVisibleColumns: [
            (selectors) => [selectors.columnFilter, selectors.visibleColumns],
            (columnFilter, visibleColumns) => filterColumns(columnFilter, visibleColumns),
        ],
        filteredHiddenColumns: [
            (selectors) => [selectors.columnFilter, selectors.hiddenColumns],
            (columnFilter, hiddenColumns) => filterColumns(columnFilter, hiddenColumns),
        ],
    },
    listeners: ({ values }) => ({
        save: () => {
            tableConfigLogic.actions.setSelectedColumns(values.visibleColumns)
        },
        resetColumns: ({ columns }) => {
            tableConfigLogic.actions.setSelectedColumns(columns)
        },
    }),
})
