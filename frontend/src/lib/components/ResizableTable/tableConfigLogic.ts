import { kea } from 'kea'
import { tableConfigLogicType } from './tableConfigLogicType'
import { userLogic } from 'scenes/userLogic'
import { UserType } from '~/types'

export const tableConfigLogic = kea<tableConfigLogicType>({
    connect: {
        logic: [userLogic],
    },
    actions: {
        setModalVisible: (visible: boolean) => ({ visible }),
        setColumnConfig: (columnConfig: string[]) => ({ columnConfig }),
        setColumnConfigSaving: (saving: boolean) => ({ saving }),
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
    },
    selectors: {
        columnConfig: [
            () => [userLogic.selectors.user],
            (user: UserType) => {
                return user?.events_column_config?.active || 'DEFAULT'
            },
        ],
        tableWidth: [
            (selectors) => [selectors.columnConfig],
            (columnConfig: [] | 'DEFAULT'): number => {
                return columnConfig === 'DEFAULT' ? 7 : columnConfig.length + 1
            },
        ],
    },
    listeners: ({ actions }) => ({
        setColumnConfig: ({ columnConfig }) => {
            actions.setColumnConfigSaving(true)
            userLogic.actions.updateUser({ events_column_config: { active: columnConfig } })
        },
        [userLogic.actionTypes.updateUserSuccess]: () => {
            actions.setColumnConfigSaving(false)
            tableConfigLogic.actions.setModalVisible(false)
        },
        [userLogic.actionTypes.updateUserFailure]: () => {
            actions.setColumnConfigSaving(false)
        },
    }),
})
