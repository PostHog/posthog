import { kea } from 'kea'
import { personalizationLogicType } from './personalizationLogicType'

export const personalizationLogic = kea<personalizationLogicType>({
    actions: {
        setStep: (step) => ({ step }),
    },
    reducers: {
        step: [null as number | null, { setStep: (_, { step }) => step }],
    },
    urlToAction: ({ actions }) => ({
        '/personalization/:step': ({ step }: { step: number | null }) => {
            actions.setStep(step)
        },
    }),
})
