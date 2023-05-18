import { kea } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import type { actionsTableLogicType } from './actionsTableLogicType'
import { ActionStepType, ActionType } from '~/types'
import { eventDefinitionsTableLogic } from 'scenes/data-management/events/eventDefinitionsTableLogic'
import api from 'lib/api'
import { urls } from '../urls'
import { lemonToast } from '@posthog/lemon-ui'
import { Link } from 'lib/lemon-ui/Link'

export const actionsTableLogic = kea<actionsTableLogicType>({
    path: ['scenes', 'actions', 'actionsTableLogic'],

    actions: () => ({
        setActionDupName: (actionDupName) => ({ actionDupName }),
        setIsActionDupModalVisible: (isActionDupModalVisible) => ({ isActionDupModalVisible }),
        setDuplicateAction: (dupAction) => ({ dupAction }),
    }),
    connect: () => ({
        actions: [actionsModel, ['loadActions'], eventDefinitionsTableLogic, ['loadEventDefinitions']],
    }),
    loaders: ({ values, actions }) => ({
        actions: {
            duplicateAction: async (): Promise<void> => {
                const action = values.dupAction
                if (action) {
                    try {
                        const { id, action_id, ...partialAction } = action
                        const newActionSteps: ActionStepType[] | undefined = action.steps?.map(
                            ({ id, ...partialStep }) => ({
                                ...partialStep,
                            })
                        )
                        await api.actions.create({
                            ...partialAction,
                            name: values.actionDupName,
                            steps: newActionSteps,
                        })
                        actions.loadActions()
                        actions.setDuplicateAction(null)
                        actions.setIsActionDupModalVisible(false)
                        lemonToast.success('Action duplicated')
                    } catch (response: any) {
                        if (response.type === 'validation_error' && response.code === 'unique') {
                            return
                        } else {
                            lemonToast.error(
                                <>
                                    Couldn't create this action. You can try{' '}
                                    <Link to={urls.createAction()}>manually creating an action instead.</Link>
                                </>
                            )
                        }
                    }
                }
            },
        },
    }),
    reducers: () => ({
        actionDupName: [
            '' as string,
            {
                setActionDupName: (_, { actionDupName }) => actionDupName,
            },
        ],
        isActionDupModalVisible: [
            false as boolean,
            {
                setIsActionDupModalVisible: (_, { isActionDupModalVisible }) => isActionDupModalVisible,
            },
        ],
        dupAction: [
            null as ActionType | null,
            {
                setDuplicateAction: (_, { dupAction }) => dupAction,
            },
        ],
    }),
})
