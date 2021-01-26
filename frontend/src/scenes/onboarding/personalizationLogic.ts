import { kea } from 'kea'
import { personalizationLogicType } from './personalizationLogicType'

const VALID_STEPS = [2] // Default is null

export const personalizationLogic = kea<personalizationLogicType>({
    actions: {
        setStep: (step) => ({ step }),
        setPersonalizationData: (payload) => ({ payload }),
        appendPersonalizationData: (payload) => ({ payload }),
    },
    reducers: {
        step: [null as number | null, { setStep: (_, { step }) => step }],
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
    urlToAction: ({ actions }) => ({
        '/personalization': (_: any, { step }: { step?: number | null }) => {
            if (step && VALID_STEPS.includes(step)) {
                actions.setStep(step)
            }
        },
    }),
})
