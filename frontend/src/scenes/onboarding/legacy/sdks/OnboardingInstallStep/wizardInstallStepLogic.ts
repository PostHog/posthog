import { actions, kea, path, reducers } from 'kea'

import type { wizardInstallStepLogicType } from './wizardInstallStepLogicType'

export const wizardInstallStepLogic = kea<wizardInstallStepLogicType>([
    path(['scenes', 'onboarding', 'wizardInstallStepLogic']),
    actions({
        setManualModalOpen: (open: boolean) => ({ open }),
        setSdkInstructionsOpen: (open: boolean) => ({ open }),
    }),
    reducers({
        manualModalOpen: [
            false,
            {
                setManualModalOpen: (_, { open }) => open,
            },
        ],
        sdkInstructionsOpen: [
            false,
            {
                setSdkInstructionsOpen: (_, { open }) => open,
            },
        ],
    }),
])
