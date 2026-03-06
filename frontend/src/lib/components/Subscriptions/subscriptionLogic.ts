import { actions, events, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { beforeUnload, router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { isEmail, isURL } from 'lib/utils'
import { getInsightId } from 'scenes/insights/utils'

import { ExportedAssetType, ExporterFormat, SubscriptionType } from '~/types'

import type { subscriptionLogicType } from './subscriptionLogicType'
import { subscriptionsLogic } from './subscriptionsLogic'
import { SubscriptionBaseProps, urlForSubscription } from './utils'

const NEW_SUBSCRIPTION: Partial<SubscriptionType> = {
    frequency: 'weekly',
    interval: 1,
    start_date: dayjs().hour(9).minute(0).second(0).toISOString(),
    target_type: 'email',
    byweekday: ['monday'],
    bysetpos: 1,
}

export interface SubscriptionsLogicProps extends SubscriptionBaseProps {
    id: number | 'new'
}
export const subscriptionLogic = kea<subscriptionLogicType>([
    path(['lib', 'components', 'Subscriptions', 'subscriptionLogic']),
    props({} as SubscriptionsLogicProps),
    key(({ id, insightShortId, dashboardId }) => `${insightShortId || dashboardId}-${id ?? 'new'}`),

    actions({
        generatePreview: true,
        setPreviewAsset: (asset: ExportedAssetType | null) => ({ asset }),
        setPreviewLoading: (loading: boolean) => ({ loading }),
        setPreviewError: (error: string | null) => ({ error }),
        setPreviewImageUrl: (url: string | null) => ({ url }),
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
                    return await api.subscriptions.get(props.id)
                }
                return { ...NEW_SUBSCRIPTION }
            },
        },
    })),

    forms(({ props, actions }) => ({
        subscription: {
            defaults: {} as unknown as SubscriptionType,
            errors: ({ frequency, interval, target_value, target_type, title, start_date }) => ({
                frequency: !frequency ? 'You need to set a schedule frequency' : undefined,
                title: !title ? 'You need to give your subscription a name' : undefined,
                interval: !interval ? 'You need to set an interval' : undefined,
                start_date: !start_date ? 'You need to set a delivery time' : undefined,
                target_type: !['slack', 'email', 'webhook'].includes(target_type)
                    ? 'Unsupported target type'
                    : undefined,
                target_value: !target_value
                    ? 'This field is required.'
                    : target_type == 'email'
                      ? !target_value
                          ? 'At least one email is required'
                          : !target_value.split(',').every((email) => isEmail(email))
                            ? 'All emails must be valid'
                            : undefined
                      : target_type == 'slack'
                        ? !target_value
                            ? 'A channel is required'
                            : undefined
                        : target_type == 'webhook'
                          ? !isURL(target_value)
                              ? 'Must be a valid URL'
                              : undefined
                          : undefined,
            }),
            submit: async (subscription, breakpoint) => {
                const insightId = props.insightShortId ? await getInsightId(props.insightShortId) : undefined

                const payload = {
                    ...subscription,
                    insight: insightId,
                    dashboard: props.dashboardId,
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

                // If a subscriptionsLogic for this insight/dashboard is mounted already, let's make sure
                // this change is propagated to `subscriptions` there
                subscriptionsLogic.findMounted(props)?.actions.loadSubscriptions()
                actions.loadSubscriptionSuccess(updatedSub)
                lemonToast.success(`Subscription saved.`)

                return updatedSub
            },
        },
    })),

    listeners(({ actions, values, props }) => ({
        setSubscriptionValue: ({ name, value }) => {
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
                })
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

    events(({ values }) => ({
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
