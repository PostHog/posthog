import { actions, afterMount, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import type { pushSubscriptionLogicType } from './pushSubscriptionLogicType'

export interface PushSubscriptionType {
    id: string
    distinct_id: string
    platform: 'android' | 'ios' | 'web'
    created_at: string
    updated_at: string
    person_email: string | null
    person_name: string | null
}

export interface PushSubscriptionLogicProps {
    platform?: 'android' | 'ios' | 'web'
}

export const pushSubscriptionLogic = kea<pushSubscriptionLogicType>([
    props({} as PushSubscriptionLogicProps),
    key((props) => props.platform ?? 'all'),
    path((key) => ['lib', 'integrations', 'pushSubscriptionLogic', key]),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    actions({
        loadPushSubscriptions: true,
    }),
    loaders(({ props, values }) => ({
        pushSubscriptions: [
            [] as PushSubscriptionType[],
            {
                loadPushSubscriptions: async (_, breakpoint) => {
                    if (!values.currentTeamId) {
                        return []
                    }
                    await breakpoint(100)
                    const response = await api.pushSubscriptionsList(values.currentTeamId)
                    let subscriptions = (response.results || []) as PushSubscriptionType[]
                    if (props.platform) {
                        subscriptions = subscriptions.filter((sub) => sub.platform === props.platform)
                    }
                    return subscriptions
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadPushSubscriptions()
    }),
    reducers({}),
    selectors({
        options: [
            (s) => [s.pushSubscriptions],
            (pushSubscriptions: PushSubscriptionType[]) => {
                return pushSubscriptions.map((sub) => {
                    const displayName = sub.person_name || sub.person_email || sub.distinct_id
                    const displayLabel = `${displayName} (${sub.platform})`
                    return {
                        key: sub.id,
                        label: displayLabel,
                    }
                })
            },
        ],
    }),
])
