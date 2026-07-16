import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { OrganizationMembershipLevel } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { organizationLogic } from 'scenes/organizationLogic'

import { requestAiAccessCreate } from 'products/platform_features/frontend/generated/api'

import type { aiConsentLogicType } from './aiConsentLogicType'

// Keep this stored across all projects, only display this once per month
const AI_DATA_PROCESSING_DISMISSED_STORAGE_KEY = `posthog_ai_data_processing_dismissed_${dayjs().format('YYYY-MM')}`

// Records, per organization, that this member has already asked an admin to enable
// PostHog AI — so the request button doesn't invite repeated submissions.
const AI_ACCESS_REQUESTED_STORAGE_KEY = 'posthog_ai_access_requested_by_org'

export const aiConsentLogic = kea<aiConsentLogicType>([
    path(['scenes', 'settings', 'organization', 'aiConsentLogic']),
    connect(() => ({
        values: [organizationLogic, ['currentOrganization']],
    })),
    actions({
        acceptDataProcessing: (testOnlyOverride?: boolean) => ({ testOnlyOverride }),
        dismissDataProcessing: true,
        requestAiAccess: true,
        markAiAccessRequested: (organizationId: string) => ({ organizationId }),
        requestAiAccessError: true,
    }),
    reducers({
        dataProcessingDismissed: [
            false,
            { persist: true, storageKey: AI_DATA_PROCESSING_DISMISSED_STORAGE_KEY },
            {
                dismissDataProcessing: () => true,
            },
        ],
        requestingAiAccess: [
            false,
            {
                requestAiAccess: () => true,
                markAiAccessRequested: () => false,
                requestAiAccessError: () => false,
            },
        ],
        aiAccessRequestedByOrg: [
            {} as Record<string, boolean>,
            { persist: true, storageKey: AI_ACCESS_REQUESTED_STORAGE_KEY },
            {
                markAiAccessRequested: (state, { organizationId }) => ({ ...state, [organizationId]: true }),
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        acceptDataProcessing: async ({ testOnlyOverride }) => {
            await organizationLogic.asyncActions.updateOrganization({
                is_ai_data_processing_approved: testOnlyOverride ?? true,
            })
        },
        requestAiAccess: async () => {
            const organization = values.currentOrganization
            if (!organization) {
                actions.requestAiAccessError()
                return
            }
            try {
                // Backend notifies the org admins/owners via a customer.io email — keeps the
                // recipient resolution server-side so it can't be tampered with from the client.
                await requestAiAccessCreate(organization.id)
                actions.markAiAccessRequested(organization.id)
                lemonToast.success('Request sent to your organization admins')
            } catch {
                actions.requestAiAccessError()
                lemonToast.error('Could not send your request. Please try again.')
            }
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
        aiAccessRequested: [
            (s) => [s.aiAccessRequestedByOrg, s.currentOrganization],
            (aiAccessRequestedByOrg, currentOrganization): boolean =>
                !!(currentOrganization && aiAccessRequestedByOrg[currentOrganization.id]),
        ],
    }),
])
