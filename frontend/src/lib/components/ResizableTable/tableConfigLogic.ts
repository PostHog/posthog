import { kea } from 'kea'
import { tableConfigLogicType } from './tableConfigLogicType'
import { userLogic } from 'scenes/userLogic'
import { UserType } from '~/types'
import { router } from 'kea-router'

export const tableConfigLogic = kea<tableConfigLogicType>({
    connect: {
        logic: [userLogic],
    },
    actions: {
        setModalVisible: (visible: boolean) => ({ visible }),
        setColumnConfig: (columnConfig: string[]) => ({ columnConfig }),
        setColumnConfigSaving: (saving: boolean) => ({ saving }),
        saveSelectedColumns: (columns: string[]) => ({ columns }),
    },
    reducers: {
        modalVisible: [
            false,
            {
                setModalVisible: (_, { visible }) => visible,
            },
        ],
        columnConfigSaving: [
            false,
            {
                setColumnConfigSaving: (_, { saving }) => saving,
            },
        ],
        columnConfig: [
            [],
            {
                setColumnConfig: (_, { columnConfig }) => columnConfig,
            },
        ],
    },
    selectors: {
        selectedColumns: [
            (selectors) => [userLogic.selectors.user, selectors.columnConfig],
            (user: UserType, columnConfig: string[]) => {
                if (columnConfig.length > 0) {
                    return columnConfig
                } else {
                    return user?.events_column_config?.active || 'DEFAULT'
                }
            },
        ],
        tableWidth: [
            (selectors) => [selectors.selectedColumns],
            (selectedColumns: [] | 'DEFAULT'): number => {
                return selectedColumns === 'DEFAULT' ? 7 : selectedColumns.length + 1
            },
        ],
        hasColumnConfigToSave: [
            (selectors) => [userLogic.selectors.user, selectors.columnConfig],
            (user: UserType, columnConfig: string[]) => {
                const hasUserSelectedColumns = columnConfig.length > 0
                const storedConfigMatchesUserSelection = columnConfig.every(
                    (v, i) => v === user?.events_column_config?.active[i]
                )
                return hasUserSelectedColumns && !storedConfigMatchesUserSelection
            },
        ],
    },
    listeners: ({ actions }) => ({
        setColumnConfig: () => {
            actions.setModalVisible(false)
        },
        saveSelectedColumns: ({ columns }) => {
            userLogic.actions.updateUser({ events_column_config: { active: columns } })
        },
        [userLogic.actionTypes.updateUserSuccess]: () => {
            actions.setColumnConfigSaving(false)
            actions.setModalVisible(false)
        },
        [userLogic.actionTypes.updateUserFailure]: () => {
            actions.setColumnConfigSaving(false)
        },
    }),
    urlToAction: ({ actions }) => ({
        '*': (_, searchParams) => {
            if (searchParams.tableColumns) {
                actions.setColumnConfig(searchParams.tableColumns)
            }
        },
    }),
    actionToUrl: ({ values }) => ({
        setColumnConfig: () => {
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
