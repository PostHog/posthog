import { kea } from 'kea'
import { personalizationLogicType } from './personalizationLogicType'

export const personalizationLogic = kea<personalizationLogicType>({
    actions: {
        setPersonalizationData: (payload) => ({ payload }),
        appendPersonalizationData: (payload) => ({ payload }),
    },
    reducers: {
        personalizationData: [
            {} as Record<string, string>,
            {
                setPersonalizationData: (_, { payload }) => payload,
                appendPersonalizationData: (state, { payload }) => {
                    return { ...state, ...payload }
                },
            },
        ],
    },
})
