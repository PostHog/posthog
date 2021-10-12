import { kea } from 'kea'
import { tableConfigLogicType } from './tableConfigLogicType'
import { router } from 'kea-router'
import { ColumnChoice } from '~/types'

export const tableConfigLogic = kea<tableConfigLogicType>({
    actions: {
        showModal: true,
        hideModal: false,
        setSelectedColumns: (columnConfig: ColumnChoice) => ({ columnConfig }), // confirmed choice, applied to table
        setUsersUnsavedSelection: (columns: string[]) => ({ columns }), // unsaved, user currently editing
        setDefaultColumns: (columns: string[]) => ({ columns }),
        setAllPossibleColumns: (columns: string[]) => ({ columns }),
    },
    reducers: {
        modalVisible: [
            false,
            {
                showModal: () => true,
                setSelectedColumns: () => false,
                hideModal: () => false,
            },
        ],
        allPossibleColumns: [
            [] as string[],
            {
                setAllPossibleColumns: (_, { columns }) => columns,
            },
        ],
        defaultColumns: [
            [] as string[],
            {
                setDefaultColumns: (_, { columns }) => columns,
            },
        ],
        usersUnsavedSelection: [
            [] as string[],
            {
                setUsersUnsavedSelection: (_, { columns }) => columns,
                setDefaultColumns: (state, { columns }) => (state.length ? state : columns),
            },
        ],
        selectedColumns: [
            'DEFAULT' as ColumnChoice,
            {
                setSelectedColumns: (_, { columnConfig }) => columnConfig,
            },
        ],
    },
    selectors: {
        tableWidth: [
            (selectors) => [selectors.selectedColumns],
            (selectedColumns: ColumnChoice): number => {
                return selectedColumns === 'DEFAULT' ? 7 : selectedColumns.length + 1
            },
        ],
        selectableColumns: [
            (selectors) => [selectors.allPossibleColumns, selectors.usersUnsavedSelection],
            (allPossibleColumns, currentlyEditingSelection) => {
                return allPossibleColumns.filter((column) => !currentlyEditingSelection.includes(column))
            },
        ],
    },
    urlToAction: ({ actions, values }) => ({
        '*': (_, searchParams) => {
            const columnsFromURL: string[] = searchParams.tableColumns
            // URL columns must be present, an array, and have content
            if (!columnsFromURL || !Array.isArray(columnsFromURL) || columnsFromURL.length === 0) {
                return
            }

            const currentColumns: ColumnChoice = values.selectedColumns

            const arrayEqualsInAnyOrder =
                columnsFromURL.length === currentColumns.length &&
                columnsFromURL.every((value) => currentColumns.includes(value))

            // URL columns should be applied if the current columns are not set, or are not the same as the URL columns
            if (currentColumns === 'DEFAULT' || !arrayEqualsInAnyOrder) {
                actions.setSelectedColumns(columnsFromURL)
            }
        },
    }),
    actionToUrl: ({ values }) => ({
        setSelectedColumns: () => {
            return [
                router.values.location.pathname,
                {
                    ...router.values.searchParams,
                    tableColumns: values.selectedColumns,
                },
                router.values.hashParams,
                { replace: true },
            ]
        },
    }),
})
