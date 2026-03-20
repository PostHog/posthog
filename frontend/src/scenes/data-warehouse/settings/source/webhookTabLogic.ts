import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { ExternalDataSource, WebhookInfo } from '~/types'

import { dataWarehouseSourceSettingsLogic } from './dataWarehouseSourceSettingsLogic'
import type { webhookTabLogicType } from './webhookTabLogicType'

export interface WebhookTabLogicProps {
    id: string
}

const REFRESH_INTERVAL = 5000

export const webhookTabLogic = kea<webhookTabLogicType>([
    props({} as WebhookTabLogicProps),
    key(({ id }: WebhookTabLogicProps) => id),
    path((key) => ['scenes', 'data-warehouse', 'settings', 'source', 'webhookTabLogic', key]),
    actions({
        createWebhook: true,
        setWebhookCreating: (creating: boolean) => ({ creating }),
        setCreateWebhookError: (error: string | null) => ({ error }),
    }),
    reducers({
        webhookCreating: [
            false,
            {
                createWebhook: () => true,
                setWebhookCreating: (_, { creating }) => creating,
            },
        ],
        createWebhookError: [
            null as string | null,
            {
                createWebhook: () => null,
                setCreateWebhookError: (_, { error }) => error,
            },
        ],
    }),
    loaders(({ props }) => ({
        webhookInfo: [
            null as WebhookInfo | null,
            {
                loadWebhookInfo: async () => {
                    return await api.externalDataSources.getWebhookInfo(props.id)
                },
            },
        ],
    })),
    selectors({
        source: [
            () => [
                (state: any, props: WebhookTabLogicProps) =>
                    dataWarehouseSourceSettingsLogic({ id: props.id, availableSources: {} }).selectors.source(state),
            ],
            (source: ExternalDataSource | null): ExternalDataSource | null => source,
        ],
        internalStateLabel: [
            (s) => [s.webhookInfo],
            (
                webhookInfo: WebhookInfo | null
            ): { label: string; tagType: 'success' | 'warning' | 'danger' | 'default' } => {
                const state = webhookInfo?.hog_function?.status?.state
                switch (state) {
                    case 1:
                        return { label: 'Healthy', tagType: 'success' }
                    case 2:
                    case 11:
                        return { label: 'Degraded', tagType: 'warning' }
                    case 3:
                    case 12:
                        return { label: 'Disabled', tagType: 'danger' }
                    default:
                        return { label: 'Unknown', tagType: 'default' }
                }
            },
        ],
        externalStateLabel: [
            (s) => [s.webhookInfo],
            (
                webhookInfo: WebhookInfo | null
            ): { label: string; tagType: 'success' | 'warning' | 'danger' | 'default' } => {
                const externalStatus = webhookInfo?.external_status
                if (!externalStatus) {
                    return { label: 'Unknown', tagType: 'default' }
                }
                if (externalStatus.error) {
                    return { label: 'Unknown', tagType: 'default' }
                }
                if (!externalStatus.exists) {
                    return { label: 'Missing', tagType: 'danger' }
                }
                switch (externalStatus.status) {
                    case 'enabled':
                        return { label: 'Active', tagType: 'success' }
                    case 'disabled':
                        return { label: 'Disabled', tagType: 'danger' }
                    default:
                        return { label: 'Unknown', tagType: 'default' }
                }
            },
        ],
        mappedTables: [
            (s) => [s.webhookInfo, s.source],
            (
                webhookInfo: WebhookInfo | null,
                source: ExternalDataSource | null
            ): { objectType: string; tableName: string }[] => {
                const mapping = webhookInfo?.schema_mapping
                if (!mapping) {
                    return []
                }
                return Object.entries(mapping).map(([objectType, schemaId]) => {
                    const schema = source?.schemas?.find((s) => s.id === schemaId)
                    return {
                        objectType,
                        tableName: schema?.name ?? schemaId,
                    }
                })
            },
        ],
    }),
    listeners(({ actions, props, cache }) => ({
        createWebhook: async () => {
            try {
                const result = await api.externalDataSources.createWebhook(props.id)
                if (result.success) {
                    lemonToast.success('Webhook created successfully')
                } else {
                    actions.setCreateWebhookError(result.error || 'Failed to create webhook')
                }
            } catch (e: any) {
                actions.setCreateWebhookError(e.message || 'Failed to create webhook')
            }
            actions.setWebhookCreating(false)
            actions.loadWebhookInfo()
        },
        loadWebhookInfoSuccess: () => {
            cache.disposables?.add(() => {
                const timerId = setTimeout(() => {
                    actions.loadWebhookInfo()
                }, REFRESH_INTERVAL)
                return () => clearTimeout(timerId)
            }, 'webhookInfoRefreshTimeout')
        },
    })),
    afterMount(({ actions }) => {
        actions.loadWebhookInfo()
    }),
])
