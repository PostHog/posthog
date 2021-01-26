import { kea } from 'kea'
import { personalizationLogicType } from './personalizationLogicType'

const VALID_STEPS = [2] // Default is null

export const personalizationLogic = kea<personalizationLogicType>({
    actions: {
        setStep: (step) => ({ step }),
    },
    reducers: {
        step: [null as number | null, { setStep: (_, { step }) => step }],
    },
    urlToAction: ({ actions }) => ({
        '/personalization': (_: any, { step }: { step?: number | null }) => {
            if (step && VALID_STEPS.includes(step)) {
                actions.setStep(step)
            }
        },
    }),
})
