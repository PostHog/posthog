import { actions, events, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { beforeUnload, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import api, { ApiError } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { recordRecentSlackChannel, slackChannelId } from 'lib/integrations/slackChannel'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { isEmail } from 'lib/utils/url'
import { getInsightId } from 'scenes/insights/utils'

import { ExportedAssetType, ExporterFormat, SubscriptionResourceTypes, SubscriptionType } from '~/types'

import type { AIWindowConfigApi } from 'products/subscriptions/frontend/generated/api.schemas'

import type { subscriptionLogicType } from './subscriptionLogicType'
import { subscriptionsLogic } from './subscriptionsLogic'
import { AI_PROMPT_MAX_LENGTH, SubscriptionBaseProps, urlForSubscription } from './utils'

function validatePrompt(
    resource_type: SubscriptionType['resource_type'],
    prompt: string | null | undefined
): string | undefined {
    if (resource_type !== SubscriptionResourceTypes.AiPrompt) {
        return undefined
    }
    const trimmedPrompt = prompt?.trim()
    if (!trimmedPrompt) {
        return 'A prompt is required for prompt subscriptions'
    }
    if (trimmedPrompt.length > AI_PROMPT_MAX_LENGTH) {
        return `Prompt cannot exceed ${AI_PROMPT_MAX_LENGTH} characters`
    }
    return undefined
}

const AI_WINDOW_MAX_DAYS = 365

function validateAiWindow(subscription: Partial<SubscriptionType>): {
    ai_prompt_config?: { window: { start_days_ago?: any; end_days_ago?: any } }
} {
    if (subscription.resource_type !== SubscriptionResourceTypes.AiPrompt) {
        return {}
    }
    const window = subscription.ai_prompt_config?.window
    const mode = window?.mode ?? 'since_last_sent'
    if (mode === 'since_last_sent') {
        return {}
    }
    const start = window?.start_days_ago
    if (start === null || start === undefined) {
        return { ai_prompt_config: { window: { start_days_ago: 'Set how many days back the report should look' } } }
    }
    if (start < 1 || start > AI_WINDOW_MAX_DAYS) {
        return { ai_prompt_config: { window: { start_days_ago: `Must be between 1 and ${AI_WINDOW_MAX_DAYS} days` } } }
    }
    if (mode === 'last_n_days') {
        return {}
    }
    const end = window?.end_days_ago
    if (end === null || end === undefined) {
        return { ai_prompt_config: { window: { end_days_ago: 'Set where the analyzed range should end' } } }
    }
    if (end < 0 || end > AI_WINDOW_MAX_DAYS) {
        return { ai_prompt_config: { window: { end_days_ago: `Must be between 0 and ${AI_WINDOW_MAX_DAYS} days` } } }
    }
    if (end >= start) {
        return { ai_prompt_config: { window: { end_days_ago: 'Must be closer to now than the start of the range' } } }
    }
    return {}
}

function validateTargetValue(target_type: string, target_value: string | undefined): string | undefined {
    if (!target_value) {
        return target_type === 'email'
            ? 'At least one email is required'
            : target_type === 'slack'
              ? 'A channel is required'
              : 'This field is required.'
    }
    if (target_type === 'email' && !target_value.split(',').every((email) => isEmail(email))) {
        return 'All emails must be valid'
    }
    return undefined
}

function validateDashboardExportInsights(
    subscription: Partial<SubscriptionType>,
    dashboardId: number | undefined
): any {
    if (subscription.resource_type === SubscriptionResourceTypes.AiPrompt || !dashboardId) {
        return undefined
    }
    return subscription.dashboard_export_insights?.length ? undefined : 'Select at least one insight'
}

function subscriptionSaveErrorMessage(error: unknown): string {
    if (error instanceof ApiError) {
        const msg = (error.detail || error.message || '').trim()
        return msg || 'Could not save subscription. Please try again.'
    }
    if (error instanceof Error && error.message) {
        return error.message
    }
    return 'Could not save subscription. Please try again.'
}

const NEW_SUBSCRIPTION: Partial<SubscriptionType> = {
    resource_type: SubscriptionResourceTypes.Insight,
    frequency: 'weekly',
    interval: 1,
    start_date: dayjs().hour(9).minute(0).second(0).toISOString(),
    target_type: 'email',
    byweekday: ['monday'],
    bysetpos: 1,
    dashboard_export_insights: [],
    integration_id: null,
    enabled: true,
    summary_enabled: false,
    summary_prompt_guide: '',
    ai_prompt_config: { window: { mode: 'since_last_sent' } },
}

export interface SubscriptionLogicProps extends SubscriptionBaseProps {
    id: number | 'new'
}
export const subscriptionLogic = kea<subscriptionLogicType>([
    path(['lib', 'components', 'Subscriptions', 'subscriptionLogic']),
    props({} as SubscriptionLogicProps),
    key(({ id, insightShortId, dashboardId }) => `${insightShortId || dashboardId}-${id ?? 'new'}`),

    actions({
        generatePreview: true,
        setPreviewAsset: (asset: ExportedAssetType | null) => ({ asset }),
        setPreviewLoading: (loading: boolean) => ({ loading }),
        setPreviewError: (error: string | null) => ({ error }),
        setPreviewImageUrl: (url: string | null) => ({ url }),
        selectAiExamplePrompt: (prompt: string, label: string, window?: AIWindowConfigApi) => ({
            prompt,
            label,
            window,
        }),
    }),

    reducers({
        previewAsset: [
            null as ExportedAssetType | null,
            {
                setPreviewAsset: (_, { asset }) => asset,
            },
        ],
        previewLoading: [
            false,
            {
                setPreviewLoading: (_, { loading }) => loading,
            },
        ],
        previewError: [
            null as string | null,
            {
                setPreviewError: (_, { error }) => error,
            },
        ],
        previewImageUrl: [
            null as string | null,
            {
                setPreviewImageUrl: (_, { url }) => url,
            },
        ],
    }),

    loaders(({ props }) => ({
        subscription: {
            __default: undefined as unknown as SubscriptionType,
            loadSubscription: async () => {
                if (props.id && props.id !== 'new') {
                    const subscription = await api.subscriptions.get(props.id)
                    // Rows created before a window was chosen carry ai_prompt_config: {} — normalise
                    // so the analysis window select renders the effective default instead of empty.
                    return {
                        ...subscription,
                        ai_prompt_config: {
                            ...subscription.ai_prompt_config,
                            window: {
                                ...subscription.ai_prompt_config?.window,
                                mode: subscription.ai_prompt_config?.window?.mode ?? 'since_last_sent',
                            },
                        },
                    }
                }
                return { ...NEW_SUBSCRIPTION }
            },
        },
        summaryQuota: {
            __default: null as { active_count: number; limit: number | null; at_limit: boolean } | null,
            loadSummaryQuota: async () => {
                return await api.subscriptions.summaryQuota()
            },
        },
    })),

    forms(({ props, actions }) => ({
        subscription: {
            defaults: { enabled: NEW_SUBSCRIPTION.enabled } as unknown as SubscriptionType,
            errors: (subscription) => ({
                frequency: !subscription.frequency ? 'You need to set a schedule frequency' : undefined,
                title: !subscription.title ? 'You need to give your subscription a name' : undefined,
                interval: !subscription.interval ? 'You need to set an interval' : undefined,
                start_date: !subscription.start_date ? 'You need to set a delivery time' : undefined,
                target_type: !['slack', 'email'].includes(subscription.target_type)
                    ? 'Unsupported target type'
                    : undefined,
                prompt: validatePrompt(subscription.resource_type, subscription.prompt),
                ...validateAiWindow(subscription),
                target_value: validateTargetValue(subscription.target_type, subscription.target_value),
                dashboard_export_insights: validateDashboardExportInsights(subscription, props.dashboardId),
            }),
            submit: async (subscription, breakpoint) => {
                const isAi = subscription.resource_type === SubscriptionResourceTypes.AiPrompt
                const insightId = !isAi && props.insightShortId ? await getInsightId(props.insightShortId) : undefined

                const payload = {
                    ...subscription,
                    insight: isAi ? undefined : insightId,
                    dashboard: isAi ? undefined : props.dashboardId,
                    // AI subscriptions have no dashboard, so a carried-over insight selection would
                    // trip the backend's "insights without a dashboard" guard. Clear it.
                    dashboard_export_insights: isAi ? [] : subscription.dashboard_export_insights,
                    // Only AI subscriptions carry a prompt; a stale one on a non-AI sub (e.g. after
                    // toggling resource_type back) would be rejected by the backend, so drop it.
                    prompt: isAi ? subscription.prompt?.trim() : undefined,
                    ai_prompt_config: isAi ? subscription.ai_prompt_config : undefined,
                }

                breakpoint()

                const updatedSub: SubscriptionType =
                    props.id === 'new'
                        ? await api.subscriptions.create(payload)
                        : await api.subscriptions.update(props.id, payload)

                actions.resetSubscription()

                if (updatedSub.id !== props.id) {
                    router.actions.replace(urlForSubscription(updatedSub.id, props))
                }

                // If a subscriptionsLogic for this insight/dashboard is mounted already, refresh both
                // its resource-scoped list and the AI subscriptions section so new entries show up
                const mountedSubscriptionsLogic = subscriptionsLogic.findMounted(props)
                mountedSubscriptionsLogic?.actions.loadSubscriptions()
                mountedSubscriptionsLogic?.actions.loadAiSubscriptions()
                actions.loadSubscriptionSuccess(updatedSub)
                actions.loadSummaryQuota()
                lemonToast.success(`Subscription saved.`)

                return updatedSub
            },
        },
    })),

    listeners(({ actions, values, props, selectors }) => ({
        submitSubscriptionSuccess: ({ subscription }) => {
            if (subscription?.target_type === 'slack' && subscription.target_value && subscription.integration_id) {
                recordRecentSlackChannel(subscription.integration_id, slackChannelId(subscription.target_value))
            }
        },
        selectAiExamplePrompt: ({ prompt, label, window }) => {
            posthog.capture('subscription_ai_example_prompt_selected', { label })
            actions.setSubscriptionValue('prompt', prompt)
            const currentMode = values.subscription?.ai_prompt_config?.window?.mode ?? 'since_last_sent'
            if (window && currentMode === 'since_last_sent') {
                // Presets that imply a timeframe prefill the analysis window — but only while the
                // window is still the default, so a deliberately-chosen one survives the click.
                // Spread keeps future sibling config keys intact.
                actions.setSubscriptionValues({
                    ai_prompt_config: { ...values.subscription?.ai_prompt_config, window },
                })
            }
        },
        submitSubscriptionFailure: ({ error }) => {
            // Kea-forms emits this when client validation fails; fields already show errors.
            if (error instanceof Error && error.message === 'Validation Failed') {
                return
            }
            const message = subscriptionSaveErrorMessage(error)
            if (error instanceof ApiError && error.attr) {
                actions.setSubscriptionManualErrors({ [error.attr]: message })
            }
            lemonToast.error(message)
        },

        setSubscriptionValue: ({ name, value }, _breakpoint, _action, previousState) => {
            const key = Array.isArray(name) ? name[0] : name
            if (key === 'frequency') {
                if (value === 'daily') {
                    actions.setSubscriptionValues({
                        bysetpos: null,
                        byweekday: null,
                    })
                } else {
                    actions.setSubscriptionValues({
                        bysetpos: NEW_SUBSCRIPTION.bysetpos,
                        byweekday: NEW_SUBSCRIPTION.byweekday,
                    })
                }
            }

            if (key === 'target_type') {
                actions.setSubscriptionValues({
                    target_value: '',
                    integration_id: null,
                })
            }

            const path = Array.isArray(name) ? name.join('.') : name
            if (path === 'ai_prompt_config.window.mode') {
                // Reducers run before listeners, so previousState tells a real mode switch (reset the
                // day bounds) apart from a same-mode re-select (keep them).
                const previousConfig = selectors.subscription(previousState)?.ai_prompt_config
                if (value !== previousConfig?.window?.mode) {
                    actions.setSubscriptionValues({
                        ai_prompt_config: { ...previousConfig, window: { mode: value } },
                    })
                }
            }
        },

        generatePreview: async (_, breakpoint) => {
            const subscription = values.subscription
            if (!subscription) {
                return
            }

            actions.setPreviewLoading(true)
            actions.setPreviewError(null)
            if (values.previewImageUrl) {
                URL.revokeObjectURL(values.previewImageUrl)
            }
            actions.setPreviewImageUrl(null)

            try {
                const insightId =
                    subscription.insight ??
                    (props.insightShortId ? await getInsightId(props.insightShortId) : undefined)
                const dashboardId = subscription.dashboard ?? props.dashboardId

                const exportData: Partial<ExportedAssetType> = {
                    export_format: ExporterFormat.PNG,
                    ...(insightId ? { insight: insightId } : {}),
                    ...(dashboardId ? { dashboard: dashboardId } : {}),
                    export_context: {
                        path: '',
                    },
                }

                const asset = await api.exports.create(exportData)
                breakpoint()

                if (asset.has_content) {
                    actions.setPreviewAsset(asset)
                    await fetchPreviewImage(asset, actions)
                } else if (asset.exception) {
                    actions.setPreviewError(asset.exception)
                } else {
                    const maxAttempts = 30
                    for (let i = 0; i < maxAttempts; i++) {
                        await new Promise((resolve) => setTimeout(resolve, 3000))
                        breakpoint()

                        const updated = await api.exports.get(asset.id)
                        if (updated.has_content) {
                            actions.setPreviewAsset(updated)
                            await fetchPreviewImage(updated, actions)
                            return
                        }
                        if (updated.exception) {
                            actions.setPreviewError(updated.exception)
                            return
                        }
                    }
                    actions.setPreviewError('Preview generation timed out. Please try again.')
                }
            } catch (e) {
                breakpoint()
                actions.setPreviewError(e instanceof Error ? e.message : 'Failed to generate preview')
            } finally {
                actions.setPreviewLoading(false)
            }
        },
    })),

    events(({ actions, values }) => ({
        afterMount: () => {
            // Load the org-wide AI summary quota once per logic mount so
            // the paywall conditional in EditSubscription has data to react
            // to without depending on URL navigation. urlToAction kept its
            // own loader call in case the user navigates between :id and
            // /new without unmounting; afterMount covers initial mount and
            // Storybook (which doesn't navigate the route).
            actions.loadSummaryQuota()
        },
        beforeUnmount: () => {
            if (values.previewImageUrl) {
                URL.revokeObjectURL(values.previewImageUrl)
            }
        },
    })),

    beforeUnload(({ actions, values }) => ({
        enabled: () => values.subscriptionChanged,
        message: 'Changes you made will be discarded.',
        onConfirm: () => {
            actions.resetSubscription()
        },
    })),

    urlToAction(({ actions }) => ({
        '/*/*/subscriptions/new': (_, searchParams) => {
            actions.loadSubscriptionSuccess({ ...NEW_SUBSCRIPTION })
            if (searchParams.target_type) {
                actions.setSubscriptionValue('target_type', searchParams.target_type)
            }
        },
        '/*/*/subscriptions/:id': () => {
            actions.loadSubscription()
        },
        '/subscriptions/new': (_, searchParams) => {
            actions.loadSubscriptionSuccess({ ...NEW_SUBSCRIPTION, resource_type: SubscriptionResourceTypes.AiPrompt })
            if (searchParams.target_type) {
                actions.setSubscriptionValue('target_type', searchParams.target_type)
            }
        },
        '/subscriptions/:id/edit': () => {
            actions.loadSubscription()
        },
    })),
])

async function fetchPreviewImage(
    asset: ExportedAssetType,
    actions: { setPreviewImageUrl: (url: string | null) => void; setPreviewError: (error: string | null) => void }
): Promise<void> {
    const url = api.exports.determineExportUrl(asset.id)
    const response = await fetch(url, { credentials: 'include' })
    if (!response.ok) {
        actions.setPreviewError('Failed to load preview image')
        return
    }
    const blob = await response.blob()
    const objectUrl = URL.createObjectURL(blob)
    actions.setPreviewImageUrl(objectUrl)
}
