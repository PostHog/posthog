import { kea } from 'kea'
import { tableConfigLogicType } from './tableConfigLogicType'
import { router } from 'kea-router'
import { ColumnChoice } from '~/types'

export const tableConfigLogic = kea<tableConfigLogicType>({
    actions: {
        showModal: true,
        hideModal: false,
        setSelectedColumns: (columnConfig: ColumnChoice) => ({ columnConfig }),
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
    },
    urlToAction: ({ actions }) => ({
        '*': (_, searchParams) => {
            if (searchParams.tableColumns) {
                actions.setSelectedColumns(searchParams.tableColumns)
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
