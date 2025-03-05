import { actions, connect, kea, listeners, path, selectors } from 'kea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'

import type { maxGlobalLogicType } from './maxGlobalLogicType'

export const maxGlobalLogic = kea<maxGlobalLogicType>([
    path(['scenes', 'max', 'maxGlobalLogic']),
    connect({
        actions: [organizationLogic, ['updateOrganization']],
        values: [organizationLogic, ['currentOrganization']],
    }),
    actions({
        acceptDataProcessing: (testOnlyOverride?: boolean) => ({ testOnlyOverride }),
    }),
    listeners(({ actions }) => ({
        acceptDataProcessing: ({ testOnlyOverride }) => {
            actions.updateOrganization({ is_ai_data_processing_approved: testOnlyOverride ?? true })
        },
    })),
    selectors({
        dataProcessingAccepted: [
            (s) => [s.currentOrganization],
            (currentOrganization): boolean => !!currentOrganization?.is_ai_data_processing_approved,
        ],
        dataProcessingApprovalDisabledReason: [
            (s) => [s.currentOrganization],
            (currentOrganization): string | null =>
                !currentOrganization?.membership_level ||
                currentOrganization.membership_level < OrganizationMembershipLevel.Admin
                    ? `Ask an admin or owner of ${currentOrganization?.name} to approve this`
                    : null,
        ],
    }),
])
