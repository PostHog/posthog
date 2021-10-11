import { kea } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { UserType } from '~/types'
import { router } from 'kea-router'

import { tableColumnsChoiceLogicType } from './tableColumnsChoiceLogicType'
export const tableColumnsChoiceLogic = kea<tableColumnsChoiceLogicType>({
    connect: {
        logic: [userLogic],
    },
    actions: {
        setModalVisible: (visible: boolean) => ({ visible }),
        setCurrentColumnChoice: (columnChoice: string[]) => ({ columnChoice }),
        setColumnChoiceSaving: (saving: boolean) => ({ saving }),
        saveSelectedColumns: (columns: string[]) => ({ columns }),
    },
    reducers: {
        modalVisible: [
            false,
            {
                setModalVisible: (_, { visible }) => visible,
            },
        ],
        columnChoiceSaving: [
            false,
            {
                setColumnChoiceSaving: (_, { saving }) => saving,
            },
        ],
        currentColumnChoice: [
            [],
            {
                setCurrentColumnChoice: (_, { columnChoice }) => columnChoice,
            },
        ],
    },
    selectors: {
        selectedColumns: [
            (selectors) => [userLogic.selectors.user, selectors.currentColumnChoice],
            (user: UserType, currentColumnChoice: string[]) => {
                if (currentColumnChoice.length > 0) {
                    return currentColumnChoice
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
            (selectors) => [userLogic.selectors.user, selectors.currentColumnChoice],
            (user: UserType, currentColumnChoice: string[]) => {
                const hasUserSelectedColumns = currentColumnChoice.length > 0
                const storedConfigMatchesUserSelection = currentColumnChoice.every(
                    (v, i) => v === user?.events_column_config?.active[i]
                )
                return hasUserSelectedColumns && !storedConfigMatchesUserSelection
            },
        ],
    },
    listeners: ({ actions }) => ({
        setCurrentColumnChoice: () => {
            actions.setModalVisible(false)
        },
        saveSelectedColumns: ({ columns }) => {
            userLogic.actions.updateUser({ events_column_config: { active: columns } })
        },
        [userLogic.actionTypes.updateUserSuccess]: () => {
            actions.setColumnChoiceSaving(false)
            const savedValues = userLogic.values?.user?.events_column_config?.active
            actions.setCurrentColumnChoice(Array.isArray(savedValues) ? savedValues : [])
            actions.setModalVisible(false)
        },
        [userLogic.actionTypes.updateUserFailure]: () => {
            actions.setColumnChoiceSaving(false)
        },
    }),
    urlToAction: ({ actions }) => ({
        '*': (_, searchParams) => {
            if (searchParams.tableColumns) {
                actions.setCurrentColumnChoice(searchParams.tableColumns)
            }
        },
    }),
    actionToUrl: ({ values }) => ({
        setCurrentColumnChoice: () => {
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
