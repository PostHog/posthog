import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { SourceConfig } from '~/queries/schema/schema-general'
import { ExternalDataSource, WebhookInfo } from '~/types'

import type { WebhookCreateResult } from '../../../shared/components/forms/WebhookSetupForm'
import { getErrorsForFields } from '../../NewSourceScene/sourceWizardLogic'
import { sourceSettingsLogic } from './sourceSettingsLogic'
import type { webhookTabLogicType } from './webhookTabLogicType'

export interface WebhookTabLogicProps {
    id: string
}

export const WEBHOOK_SECTIONS = ['overview', 'configuration', 'activity'] as const
export type WebhookSection = (typeof WEBHOOK_SECTIONS)[number]
export const DEFAULT_WEBHOOK_SECTION: WebhookSection = 'overview'

// A source without automatic reconcile support (base no-op sync_webhook_events) reports
// success while missing_events stays non-empty, so "success" alone must not be announced
// as the provider having been updated.
export function syncWebhookEventsToast(
    success: boolean,
    error: string | null | undefined,
    missingEvents: string[] | undefined
): { type: 'success' | 'info' | 'error'; message: string } {
    if (!success) {
        return { type: 'error', message: error ?? 'Failed to update webhook on the source' }
    }
    if ((missingEvents?.length ?? 0) > 0) {
        return {
            type: 'info',
            message:
                'Webhook checked, but some events could not be added automatically. Add them in your source dashboard following the instructions below.',
        }
    }
    return { type: 'success', message: 'Webhook updated' }
}

export const webhookTabLogic = kea<webhookTabLogicType>([
    props({} as WebhookTabLogicProps),
    key(({ id }: WebhookTabLogicProps) => id),
    path((key) => ['products', 'dataWarehouse', 'webhookTabLogic', key]),
    actions({
        createWebhook: true,
        setWebhookCreating: (creating: boolean) => ({ creating }),
        setCreateWebhookResult: (result: WebhookCreateResult | null) => ({
            result,
        }),
        submitWebhookFields: true,
        syncWebhookEvents: true,
        setWebhookSyncing: (syncing: boolean) => ({ syncing }),
        deleteWebhook: true,
        setWebhookDeleting: (deleting: boolean) => ({ deleting }),
        setCurrentSection: (section: WebhookSection) => ({ section }),
        _setCurrentSection: (section: WebhookSection) => ({ section }),
    }),
    reducers({
        currentSection: [
            DEFAULT_WEBHOOK_SECTION as WebhookSection,
            {
                setCurrentSection: (_, { section }) => section,
                _setCurrentSection: (_, { section }) => section,
            },
        ],
        webhookCreating: [
            false,
            {
                createWebhook: () => true,
                setWebhookCreating: (_, { creating }) => creating,
            },
        ],
        createWebhookResult: [
            null as WebhookCreateResult | null,
            {
                createWebhook: () => null,
                setCreateWebhookResult: (_, { result }) => result,
            },
        ],
        webhookSyncing: [
            false,
            {
                syncWebhookEvents: () => true,
                setWebhookSyncing: (_, { syncing }) => syncing,
            },
        ],
        webhookDeleting: [
            false,
            {
                deleteWebhook: () => true,
                setWebhookDeleting: (_, { deleting }) => deleting,
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
                    sourceSettingsLogic({ id: props.id, availableSources: {} }).selectors.source(state),
            ],
            (source: ExternalDataSource | null): ExternalDataSource | null => source,
        ],
        sourceConfig: [
            () => [
                (state: any, props: WebhookTabLogicProps) =>
                    sourceSettingsLogic({
                        id: props.id,
                        availableSources: {},
                    }).selectors.sourceFieldConfig(state),
            ],
            (sourceFieldConfig: SourceConfig | null): SourceConfig | null => sourceFieldConfig,
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
        hasWebhookSchemas: [
            (s) => [s.source],
            (source: ExternalDataSource | null): boolean => {
                if (!source?.schemas) {
                    return false
                }
                return source.schemas.some((s) => s.sync_type === 'webhook' && s.should_sync)
            },
        ],
        canDeleteWebhook: [
            (s) => [s.webhookInfo, s.hasWebhookSchemas],
            (webhookInfo: WebhookInfo | null, hasWebhookSchemas: boolean): boolean => {
                return !!webhookInfo?.exists && !hasWebhookSchemas
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
    forms(({ values, actions }) => ({
        webhookFieldInputs: {
            defaults: {} as Record<string, any>,
            errors: (sourceValues) => {
                const webhookFields = values.sourceConfig?.webhookFields ?? []
                return getErrorsForFields(
                    webhookFields,
                    {
                        prefix: '',
                        payload: sourceValues as Record<string, any>,
                    },
                    // In edit mode, secret fields whose current value is the masked
                    // `{secret: true}` marker are already set on the server. Treat
                    // them as satisfying the required check so users can update other
                    // fields without re-entering the secret.
                    { allowBlankSensitiveFields: true }
                ).payload
            },
            submit: async () => {
                actions.submitWebhookFields()
            },
        },
    })),
    actionToUrl(({ values }) => ({
        setCurrentSection: () => {
            return [
                router.values.location.pathname,
                { ...router.values.searchParams, section: values.currentSection },
                router.values.hashParams,
            ]
        },
    })),
    urlToAction(({ actions, values }) => ({
        '*': (_, searchParams): void => {
            // Reset to default when no/invalid ?section= so the UI matches the deep link.
            const possibleSection = searchParams.section as WebhookSection | undefined
            const nextSection: WebhookSection = WEBHOOK_SECTIONS.includes(possibleSection as WebhookSection)
                ? (possibleSection as WebhookSection)
                : DEFAULT_WEBHOOK_SECTION
            if (nextSection !== values.currentSection) {
                actions._setCurrentSection(nextSection)
            }
        },
    })),
    listeners(({ actions, props, values }) => ({
        loadWebhookInfoSuccess: ({ webhookInfo }) => {
            // Server returns each input either as `{secret: true}` (masked) or `{value: ...}`
            // (HogFunctionSerializer convention). Unwrap non-secret values and use them as
            // the form's new defaults via reset — that way any stale plaintext typed in a
            // prior edit gets cleared, and `webhookFieldInputsChanged` only flips when the
            // user actually edits a field. Mirrors the HogFunctions configuration logic
            // pattern (`loadHogFunctionSuccess: () => actions.resetForm()`).
            const inputs = webhookInfo?.inputs
            const nonSecretValues: Record<string, any> = {}
            if (inputs) {
                for (const [name, entry] of Object.entries(inputs)) {
                    if (entry && typeof entry === 'object' && !Array.isArray(entry) && 'value' in entry) {
                        nonSecretValues[name] = (entry as { value: unknown }).value
                    }
                }
            }
            actions.resetWebhookFieldInputs(nonSecretValues)
        },
        createWebhook: async () => {
            try {
                const result = await api.externalDataSources.createWebhook(props.id)
                actions.setCreateWebhookResult(result)
                if (result.success) {
                    if ((result.pending_inputs?.length ?? 0) === 0) {
                        lemonToast.success('Webhook created successfully')
                    } else {
                        lemonToast.info('Webhook created — enter the remaining details below to finish setup')
                    }
                }
            } catch (e: any) {
                actions.setCreateWebhookResult({
                    success: false,
                    webhook_url: '',
                    error: e.data?.message ?? e.message ?? 'Failed to create webhook',
                })
            }
            actions.setWebhookCreating(false)
            actions.loadWebhookInfo()
        },
        submitWebhookFields: async () => {
            // Only send fields that have a truthy value. Empty strings for fields the
            // user never touched (e.g. a masked secret left alone) must not overwrite
            // the existing server value.
            const payload = Object.fromEntries(
                Object.entries(values.webhookFieldInputs).filter(([, value]) => {
                    if (value === undefined || value === null || value === '') {
                        return false
                    }
                    return true
                })
            )
            if (Object.keys(payload).length === 0) {
                lemonToast.info('No changes to save')
                return
            }
            try {
                await api.externalDataSources.updateWebhookInputs(props.id, payload)
                lemonToast.success('Webhook inputs saved')
                // Clear typed plaintext immediately so the form doesn't keep the rotated
                // secret in client state. `loadWebhookInfoSuccess` will then re-seed
                // defaults from the masked server response.
                actions.resetWebhookFieldInputs()
                actions.loadWebhookInfo()
            } catch (e: any) {
                lemonToast.error(e.data?.message ?? e.message ?? 'Failed to update webhook inputs')
            }
        },
        syncWebhookEvents: async () => {
            try {
                const result = await api.externalDataSources.syncWebhookEvents(props.id)
                // The response carries the refreshed webhook_info payload, so update in place
                // via the loader success action instead of firing a second GET.
                const { success, error, ...webhookInfo } = result
                actions.loadWebhookInfoSuccess(webhookInfo)
                const toast = syncWebhookEventsToast(success, error, webhookInfo.missing_events)
                lemonToast[toast.type](toast.message)
            } catch (e: any) {
                lemonToast.error(e.data?.message ?? e.message ?? 'Failed to update webhook')
            }
            actions.setWebhookSyncing(false)
        },
        deleteWebhook: async () => {
            try {
                const result = await api.externalDataSources.deleteWebhook(props.id)
                if (result.success) {
                    lemonToast.success(
                        result.external_deleted
                            ? 'Webhook deleted from source and PostHog'
                            : 'Webhook deleted from PostHog'
                    )
                    if (result.error) {
                        lemonToast.warning(result.error)
                    }
                } else {
                    lemonToast.error(result.error ?? 'Failed to delete webhook')
                }
            } catch (e: any) {
                lemonToast.error(e.data?.message ?? e.message ?? 'Failed to delete webhook')
            }
            actions.setWebhookDeleting(false)
            actions.loadWebhookInfo()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadWebhookInfo()
    }),
])
