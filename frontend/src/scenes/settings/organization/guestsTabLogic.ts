import { actions, kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'

import api, { PaginatedResponse } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { organizationLogic } from 'scenes/organizationLogic'

import { OrganizationMemberType } from '~/types'

import type { guestsTabLogicType } from './guestsTabLogicType'

export const guestsTabLogic = kea<guestsTabLogicType>([
    path(['scenes', 'organization', 'Settings', 'guestsTabLogic']),
    actions({
        promoteGuest: (userUuid: string) => ({ userUuid }),
    }),
    loaders(() => ({
        guests: [
            [] as OrganizationMemberType[],
            {
                loadGuests: async () => {
                    const orgId = organizationLogic.values.currentOrganizationId
                    if (!orgId) {
                        return []
                    }
                    const response = await api.get<PaginatedResponse<OrganizationMemberType>>(
                        `api/organizations/${orgId}/members/?guests_only=true`
                    )
                    return response.results
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        promoteGuest: async ({ userUuid }) => {
            const orgId = organizationLogic.values.currentOrganizationId
            if (!orgId) {
                return
            }
            try {
                await api.create(`api/organizations/${orgId}/members/${userUuid}/promote_guest/`, {})
                lemonToast.success('Guest promoted to member')
                actions.loadGuests()
            } catch {
                lemonToast.error('Failed to promote guest to member')
            }
        },
    })),
])
