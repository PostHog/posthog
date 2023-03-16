import { actions, kea, path, reducers } from 'kea'
import { userInterviewSchedulerLogicType } from './userInterviewSchedulerLogicType'

export const userInterviewSchedulerLogic = kea<userInterviewSchedulerLogicType>([
    path(['scenes', 'feedback', 'userInterviewSchedulerLogic']),
    actions({
        toggleSchedulerInstructions: true,
    }),
    reducers({
        schedulerInstructions: [
            false as boolean,
            {
                toggleSchedulerInstructions: (state) => !state,
            },
        ],
    }),
])
