import { actions, connect, kea, listeners, path, reducers } from 'kea'

import { organizationLogic } from '~/scenes/organizationLogic'
import { projectLogic } from '~/scenes/projectLogic'

import type { modalInterruptionTrackingLogicType } from './modalInterruptionTrackingLogicType'

export const modalInterruptionTrackingLogic = kea<modalInterruptionTrackingLogicType>([
    path(['lib', 'components', 'TimeSensitiveAuthentication', 'modalInterruptionTrackingLogic']),
    connect(() => {
        try {
            // Use lazy require to avoid circular dependencies
            const { globalModalsLogic } = require('~/layout/GlobalModals')

            return {
                values: [globalModalsLogic, ['isCreateOrganizationModalShown', 'isCreateProjectModalShown']],
                actions: [organizationLogic, ['createOrganization'], projectLogic, ['createProject']],
            }
        } catch {
            // Safe fallback for tests
            return {}
        }
    }),
    actions({
        setInterruptedForm: (form: string | null) => ({ form }),
    }),
    reducers({
        interruptedForm: [
            null as string | null,
            {
                setInterruptedForm: (_, { form }) => form,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        createOrganization: () => {
            if ((values as any).isCreateOrganizationModalShown) {
                actions.setInterruptedForm('create_organization_modal')
            }
        },

        createProject: () => {
            if ((values as any).isCreateProjectModalShown) {
                actions.setInterruptedForm('create_project_modal')
            }
        },
    })),
])
