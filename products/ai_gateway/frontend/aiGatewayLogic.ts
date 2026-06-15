import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import type { aiGatewayLogicType } from './aiGatewayLogicType'
import { fetchGatewayUsage, GatewayUsage } from './gatewayUsage'
import { gatewaysList, gatewaysPartialUpdate } from './generated/api'
import { GatewayApi } from './generated/api.schemas'

// Mirrors the backend GATEWAY_SLUG_PATTERN — lowercase, URL-safe, no leading/trailing separator.
const SLUG_PATTERN = /^[a-z0-9]+(?:[_-][a-z0-9]+)*$/

// `null` = modal closed, a string id = renaming that gateway.
export type EditingGatewayId = string | null

export interface GatewayFormValues {
    slug: string
}

export const aiGatewayLogic = kea<aiGatewayLogicType>([
    path(['products', 'ai_gateway', 'frontend', 'aiGatewayLogic']),
    connect(() => ({ values: [teamLogic, ['currentTeamId']] })),
    actions({
        openEditGateway: (gateway: GatewayApi) => ({ gateway }),
        closeModal: true,
    }),
    loaders(({ values }) => ({
        gateways: [
            [] as GatewayApi[],
            {
                // One gateway per team; listed so the scene can link to and rename it.
                loadGateways: async () => {
                    return (await gatewaysList(String(values.currentTeamId), { limit: 1000 })).results
                },
            },
        ],
        usage: [
            null as GatewayUsage | null,
            {
                // Project-wide usage across every gateway-attributed event.
                loadUsage: async () => await fetchGatewayUsage(),
            },
        ],
    })),
    reducers({
        editingGatewayId: [
            null as EditingGatewayId,
            {
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
                if (!values.editingGatewayId) {
                    return
                }
                try {
                    await gatewaysPartialUpdate(projectId, values.editingGatewayId, { slug: trimmed })
                } catch (error: any) {
                    // Surface the backend's field error (e.g. invalid slug) on the input.
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
    listeners(({ actions }) => ({
        openEditGateway: ({ gateway }) => actions.resetEditingGateway({ slug: gateway.slug }),
    })),
    afterMount(({ actions }) => {
        actions.loadGateways()
        actions.loadUsage()
    }),
])
