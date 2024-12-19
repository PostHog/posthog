import { actions, kea, path, reducers, selectors } from 'kea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'

import type { maxGlobalLogicType } from './maxGlobalLogicType'

export const maxGlobalLogic = kea<maxGlobalLogicType>([
    path(['scenes', 'max', 'maxGlobalLogic']),
    actions({
        acceptDataProcessing: (testOnlyOverride?: boolean) => ({ testOnlyOverride }),
    }),
    reducers({
        dataProcessingAccepted: [
            false,
            { persist: true },
            {
                acceptDataProcessing: (_, { testOnlyOverride }) => testOnlyOverride ?? true,
            },
        ],
    }),
    selectors({
        dataProcessingApprovalDisabledReason: [
            () => [organizationLogic.selectors.currentOrganization],
            (currentOrganization): string | null =>
                !currentOrganization || currentOrganization.membership_level < OrganizationMembershipLevel.Admin
                    ? `Ask an organization admin or owner to approve OpenAI-based analysis in ${
                          currentOrganization?.name || 'this organization'
                      }`
                    : null,
        ],
    }),
])
