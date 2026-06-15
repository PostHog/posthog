import { actions, afterMount, isBreakpoint, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api, { CountedPaginatedResponse } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { OrganizationMemberType } from '~/types'

import type { accountRelatedUsersLogicType } from './accountRelatedUsersLogicType'

// The account org-members endpoint returns a slim member shape — only id + user are serialized.
export type AccountOrganizationMember = Pick<OrganizationMemberType, 'id' | 'user'>

export const PAGE_SIZE = 5

export interface AccountRelatedUsersLogicProps {
    externalId: string
}

export const accountRelatedUsersLogic = kea<accountRelatedUsersLogicType>([
    path((key) => ['scenes', 'customerAnalytics', 'accounts', 'accountRelatedUsersLogic', key]),
    props({} as AccountRelatedUsersLogicProps),
    // Accounts with no external_id all share the empty-string key, which is benign: afterMount skips loading when externalId is falsy.
    key((props) => props.externalId),
    actions({
        setPage: (page: number) => ({ page }),
    }),
    reducers({
        page: [
            1,
            {
                setPage: (_, { page }) => page,
            },
        ],
    }),
    loaders(({ props, values }) => ({
        membersResponse: [
            null as CountedPaginatedResponse<AccountOrganizationMember> | null,
            {
                loadMembers: async (_ = null, breakpoint) => {
                    try {
                        const response = await api.organizationMembers.listForOrg(props.externalId, {
                            limit: PAGE_SIZE,
                            offset: (values.page - 1) * PAGE_SIZE,
                        })
                        breakpoint()
                        return response
                    } catch (error) {
                        if (!isBreakpoint(error as Error)) {
                            posthog.captureException(error as Error, {
                                scope: 'accountRelatedUsersLogic.loadMembers',
                            })
                            lemonToast.error('Failed to load related users')
                        }
                        throw error
                    }
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        setPage: () => actions.loadMembers(),
    })),
    afterMount(({ actions, props }) => {
        if (props.externalId) {
            actions.loadMembers()
        }
    }),
])
