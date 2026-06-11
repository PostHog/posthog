import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import type { aiGatewayLogicType } from './aiGatewayLogicType'
import { fetchGatewayUsage, GatewayUsage } from './gatewayUsage'
import {
    gatewaysAssignableCredentialsList,
    gatewaysAssignCredentialCreate,
    gatewaysCreate,
    gatewaysCredentialsRetrieve,
    gatewaysDestroy,
    gatewaysList,
    gatewaysPartialUpdate,
    gatewaysUnassignCredentialCreate,
} from './generated/api'
import { AssignableCredentialApi, GatewayApi, GatewayBoundCredentialsApi } from './generated/api.schemas'

// Mirrors the backend GATEWAY_SLUG_PATTERN — lowercase, URL-safe, no leading/trailing separator.
const SLUG_PATTERN = /^[a-z0-9]+(?:[_-][a-z0-9]+)*$/

// `null` = modal closed, `'new'` = creating, a string id = renaming that gateway.
export type EditingGatewayId = string | 'new' | null

export type CredentialType = 'project_secret_api_key' | 'oauth_application'

export interface GatewayFormValues {
    slug: string
}

export const aiGatewayLogic = kea<aiGatewayLogicType>([
    path(['products', 'ai_gateway', 'frontend', 'aiGatewayLogic']),
    connect(() => ({ values: [teamLogic, ['currentTeamId']] })),
    actions({
        openNewGateway: true,
        openEditGateway: (gateway: GatewayApi) => ({ gateway }),
        closeModal: true,
        deleteGateway: (gateway: GatewayApi) => ({ gateway }),
        assignCredential: (payload: { credentialId: string; gatewayId: string }) => payload,
        unassignCredential: (payload: { credentialType: CredentialType; credentialId: string; gatewayId: string }) =>
            payload,
    }),
    loaders(({ values }) => ({
        gateways: [
            [] as GatewayApi[],
            {
                loadGateways: async () => {
                    return (await gatewaysList(String(values.currentTeamId), { limit: 1000 })).results
                },
            },
        ],
        credentialsByGateway: [
            {} as Record<string, GatewayBoundCredentialsApi>,
            {
                loadCredentials: async ({ gatewayId }: { gatewayId: string }) => ({
                    ...values.credentialsByGateway,
                    [gatewayId]: await gatewaysCredentialsRetrieve(String(values.currentTeamId), gatewayId),
                }),
            },
        ],
        usage: [
            null as GatewayUsage | null,
            {
                // Project-wide usage across every gateway-attributed event.
                loadUsage: async () => await fetchGatewayUsage(),
            },
        ],
        assignableCredentials: [
            [] as AssignableCredentialApi[],
            {
                // The team's llm_gateway:read project secret keys not yet assigned to a gateway.
                loadAssignableCredentials: async () =>
                    await gatewaysAssignableCredentialsList(String(values.currentTeamId)),
            },
        ],
    })),
    reducers({
        editingGatewayId: [
            null as EditingGatewayId,
            {
                openNewGateway: () => 'new',
                openEditGateway: (_, { gateway }) => gateway.id,
                closeModal: () => null,
            },
        ],
    }),
    forms(({ values, actions }) => ({
        editingGateway: {
            defaults: { slug: '' } as GatewayFormValues,
            errors: ({ slug }: GatewayFormValues) => ({
                slug: !slug?.trim()
                    ? 'A slug is required'
                    : !SLUG_PATTERN.test(slug.trim())
                      ? "Use lowercase letters, digits, '-' or '_' (no spaces or leading/trailing separator)"
                      : undefined,
            }),
            submit: async ({ slug }: GatewayFormValues) => {
                const projectId = String(values.currentTeamId)
                const trimmed = slug.trim()
                try {
                    if (values.editingGatewayId && values.editingGatewayId !== 'new') {
                        await gatewaysPartialUpdate(projectId, values.editingGatewayId, { slug: trimmed })
                    } else {
                        await gatewaysCreate(projectId, { slug: trimmed })
                    }
                } catch (error: any) {
                    // Surface the backend's field error (e.g. duplicate slug) on the input.
                    const detail = error?.data?.detail ?? error?.detail
                    if (error?.data?.attr === 'slug' && detail) {
                        actions.setEditingGatewayManualErrors({ slug: detail })
                        return
                    }
                    lemonToast.error('Could not save gateway')
                    return
                }
                actions.loadGateways()
                actions.closeModal()
                lemonToast.success('Gateway saved')
            },
        },
    })),
    listeners(({ values, actions }) => ({
        openNewGateway: () => actions.resetEditingGateway({ slug: '' }),
        openEditGateway: ({ gateway }) => actions.resetEditingGateway({ slug: gateway.slug }),
        deleteGateway: async ({ gateway }) => {
            try {
                await gatewaysDestroy(String(values.currentTeamId), gateway.id)
                actions.loadGateways()
                lemonToast.success(`Deleted gateway "${gateway.slug}"`)
            } catch {
                lemonToast.error('Could not delete gateway')
            }
        },
        assignCredential: async ({ credentialId, gatewayId }) => {
            try {
                await gatewaysAssignCredentialCreate(String(values.currentTeamId), gatewayId, {
                    credential_id: credentialId,
                })
            } catch {
                lemonToast.error('Could not assign key')
                return
            }
            actions.loadGateways()
            actions.loadCredentials({ gatewayId })
            actions.loadAssignableCredentials()
            lemonToast.success('Key assigned')
        },
        unassignCredential: async ({ credentialType, credentialId, gatewayId }) => {
            try {
                await gatewaysUnassignCredentialCreate(String(values.currentTeamId), gatewayId, {
                    credential_type: credentialType,
                    credential_id: credentialId,
                })
            } catch {
                lemonToast.error('Could not remove key')
                return
            }
            actions.loadGateways()
            actions.loadCredentials({ gatewayId })
            actions.loadAssignableCredentials()
            lemonToast.success('Key removed from gateway')
        },
    })),
    afterMount(({ actions }) => {
        actions.loadGateways()
        actions.loadUsage()
        actions.loadAssignableCredentials()
    }),
])
