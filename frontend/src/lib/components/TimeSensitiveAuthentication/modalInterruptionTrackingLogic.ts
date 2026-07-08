import { actions, connect, kea, listeners, path, reducers } from 'kea'

import { globalModalsLogic } from '~/layout/globalModalsLogic'
import { organizationLogic } from '~/scenes/organizationLogic'
import { projectLogic } from '~/scenes/projectLogic'

import type { modalInterruptionTrackingLogicType } from './modalInterruptionTrackingLogicType'

export const modalInterruptionTrackingLogic = kea<modalInterruptionTrackingLogicType>([
    path(['lib', 'components', 'TimeSensitiveAuthentication', 'modalInterruptionTrackingLogic']),
    connect(() => ({
        values: [globalModalsLogic, ['isCreateOrganizationModalShown', 'isCreateProjectModalShown']],
        actions: [organizationLogic, ['createOrganization'], projectLogic, ['createProject']],
    })),
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
            if (values.isCreateOrganizationModalShown) {
                actions.setInterruptedForm('create_organization_modal')
            }
        },

        createProject: () => {
            if (values.isCreateProjectModalShown) {
                actions.setInterruptedForm('create_project_modal')
            }
        },
    })),
])
