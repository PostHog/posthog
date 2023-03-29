import { actions, kea, path, reducers } from 'kea'
import { automationStepConfigLogicType } from './automationStepConfigLogicType'
import { AnyAutomationStep } from './schema'

export const automationStepConfigLogic = kea<automationStepConfigLogicType>([
    path(['scenes', 'automations', 'automationStepConfigLogic']),
    actions({
        openStepConfig: true,
        closeStepConfig: true,
        setStep: (step: AnyAutomationStep) => ({ step }),
    }),
    reducers({
        stepConfigOpen: [
            true as boolean,
            {
                openStepConfig: () => true,
                closeStepConfig: () => false,
            },
        ],
        step: [
            null as null | AnyAutomationStep,
            {
                setStep: (_, { step }) => step,
            },
        ],
    }),
])
