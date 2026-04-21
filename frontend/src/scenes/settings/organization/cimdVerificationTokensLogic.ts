import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api, { PaginatedResponse } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { organizationLogic } from 'scenes/organizationLogic'

import type { cimdVerificationTokensLogicType } from './cimdVerificationTokensLogicType'

export interface CIMDVerificationToken {
    id: string
    label: string
    mask_value: string | null
    created_by: { first_name: string; email: string } | null
    created_at: string
    last_used_at: string | null
}

export interface CIMDVerificationTokenWithValue extends CIMDVerificationToken {
    value: string
}

const listUrl = (orgId: string): string => `api/organizations/${orgId}/cimd_verification_tokens/`

export const cimdVerificationTokensLogic = kea<cimdVerificationTokensLogicType>([
    path(['scenes', 'settings', 'organization', 'cimdVerificationTokensLogic']),

    actions({
        showCreateDialog: true,
        hideCreateDialog: true,
        setNewTokenLabel: (label: string) => ({ label }),
        setJustCreatedToken: (token: CIMDVerificationTokenWithValue | null) => ({ token }),
        createToken: true,
        deleteToken: (token: CIMDVerificationToken) => ({ token }),
    }),

    reducers({
        isCreateDialogOpen: [
            false,
            {
                showCreateDialog: () => true,
                hideCreateDialog: () => false,
            },
        ],
        newTokenLabel: [
            '',
            {
                setNewTokenLabel: (_, { label }) => label,
                hideCreateDialog: () => '',
                createToken: () => '',
            },
        ],
        justCreatedToken: [
            null as CIMDVerificationTokenWithValue | null,
            {
                setJustCreatedToken: (_, { token }) => token,
            },
        ],
    }),

    loaders({
        tokens: [
            [] as CIMDVerificationToken[],
            {
                loadTokens: async () => {
                    const orgId = organizationLogic.values.currentOrganization?.id
                    if (!orgId) {
                        return []
                    }
                    const response = await api.get<PaginatedResponse<CIMDVerificationToken>>(listUrl(orgId))
                    return response.results
                },
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        createToken: async () => {
            const orgId = organizationLogic.values.currentOrganization?.id
            if (!orgId) {
                return
            }
            const label = values.newTokenLabel.trim()
            if (!label) {
                lemonToast.error('Please enter a label for this token.')
                return
            }
            try {
                const created = await api.create<CIMDVerificationTokenWithValue>(listUrl(orgId), { label })
                actions.setJustCreatedToken(created)
                actions.hideCreateDialog()
                actions.loadTokens()
            } catch (e: any) {
                lemonToast.error(e?.detail || 'Failed to create token')
            }
        },
        deleteToken: async ({ token }) => {
            const orgId = organizationLogic.values.currentOrganization?.id
            if (!orgId) {
                return
            }
            try {
                await api.delete(`${listUrl(orgId)}${token.id}/`)
                lemonToast.success('Token revoked')
                actions.loadTokens()
            } catch (e: any) {
                lemonToast.error(e?.detail || 'Failed to revoke token')
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadTokens()
    }),
])
