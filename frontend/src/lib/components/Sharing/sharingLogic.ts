import { afterMount, kea, key, path, props } from 'kea'
import { InsightShortId, SharingConfigurationType } from '~/types'

import api from 'lib/api'
import { loaders } from 'kea-loaders'
import { getInsightId } from 'scenes/insights/utils'

import type { sharingLogicType } from './sharingLogicType'

export interface SharingLogicProps {
    dashboardId?: number
    insightShortId?: InsightShortId
}

const propsToApiParams = async (props: SharingLogicProps): Promise<{ dashboardId?: number; insightId?: number }> => {
    const insightId = props.insightShortId ? await getInsightId(props.insightShortId) : undefined
    return {
        dashboardId: props.dashboardId,
        insightId,
    }
}

export const sharingLogic = kea<sharingLogicType>([
    path(['lib', 'components', 'Sharing', 'sharingLogic']),
    props({} as SharingLogicProps),
    key(({ insightShortId, dashboardId }) => `sharing-${insightShortId || dashboardId}`),

    loaders(({ props }) => ({
        sharingConfiguration: {
            __default: undefined as unknown as SharingConfigurationType,
            loadSharingConfiguration: async () => {
                return await api.sharing.get(await propsToApiParams(props))
            },
            setIsEnabled: async (enabled: boolean) => {
                return await api.sharing.update(await propsToApiParams(props), { enabled })
            },
        },
    })),

    // forms(({ props, actions, values }) => ({
    //     subscription: {
    //         defaults: {} as unknown as SubscriptionType,
    //         errors: ({ frequency, interval, target_value, target_type, title, start_date }) => ({
    //             frequency: !frequency ? 'You need to set a schedule frequency' : undefined,
    //             title: !title ? 'You need to give your subscription a name' : undefined,
    //             interval: !interval ? 'You need to set an interval' : undefined,
    //             start_date: !start_date ? 'You need to set a delivery time' : undefined,
    //             target_type: !['slack', 'email', 'webhook'].includes(target_type)
    //                 ? 'Unsupported target type'
    //                 : undefined,
    //             target_value: !target_value
    //                 ? 'This field is required.'
    //                 : target_type == 'email'
    //                 ? !target_value
    //                     ? 'At least one email is required'
    //                     : !target_value.split(',').every((email) => isEmail(email))
    //                     ? 'All emails must be valid'
    //                     : undefined
    //                 : target_type == 'slack'
    //                 ? !target_value
    //                     ? 'A channel is required'
    //                     : undefined
    //                 : target_type == 'webhook'
    //                 ? !isURL(target_value)
    //                     ? 'Must be a valid URL'
    //                     : undefined
    //                 : undefined,
    //             memberOfSlackChannel:
    //                 target_type == 'slack'
    //                     ? !values.isMemberOfSlackChannel(target_value)
    //                         ? 'Please add the PostHog Slack App to the selected channel'
    //                         : undefined
    //                     : undefined,
    //         }),
    //         submit: async (subscription, breakpoint) => {
    //             const insightId = props.insightShortId ? await getInsightId(props.insightShortId) : undefined

    //             const payload = {
    //                 ...subscription,
    //                 insight: insightId,
    //                 dashboard: props.dashboardId,
    //             }

    //             breakpoint()

    //             const updatedSub: SubscriptionType =
    //                 props.id === 'new'
    //                     ? await api.subscriptions.create(payload)
    //                     : await api.subscriptions.update(props.id, payload)

    //             actions.resetSubscription()

    //             if (updatedSub.id !== props.id) {
    //                 router.actions.replace(urlForSubscription(updatedSub.id, props))
    //             }

    //             actions.loadSubscriptions()
    //             actions.loadSubscriptionSuccess(updatedSub)
    //             lemonToast.success(`Subscription saved.`)

    //             return updatedSub
    //         },
    //     },
    // })),

    // listeners(({ actions }) => ({
    //     setSubscriptionValue: ({ name, value }) => {
    //         const key = Array.isArray(name) ? name[0] : name
    //         if (key === 'frequency') {
    //             if (value === 'daily') {
    //                 actions.setSubscriptionValues({
    //                     bysetpos: null,
    //                     byweekday: null,
    //                 })
    //             } else {
    //                 actions.setSubscriptionValues({
    //                     bysetpos: NEW_SUBSCRIPTION.bysetpos,
    //                     byweekday: NEW_SUBSCRIPTION.byweekday,
    //                 })
    //             }
    //         }

    //         if (key === 'target_type') {
    //             actions.setSubscriptionValues({
    //                 target_value: '',
    //             })
    //         }
    //     },
    // })),
    // beforeUnload(({ actions, values }) => ({
    //     enabled: () => values.subscriptionChanged,
    //     message: 'Changes you made will be discarded.',
    //     onConfirm: () => {
    //         actions.resetSubscription()
    //     },
    // })),

    afterMount(({ actions }) => {
        actions.loadSharingConfiguration()
    }),
])
