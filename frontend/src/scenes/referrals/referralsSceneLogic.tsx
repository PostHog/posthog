import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { organizationLogic } from 'scenes/organizationLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { Breadcrumb, UserType } from '~/types'

function socialReferralSignupUrl(distinctId: string): string {
    const url = new URL(urls.signup(), document.baseURI)
    url.searchParams.set('referral_id', distinctId)
    url.searchParams.set('utm_medium', 'in-product')
    url.searchParams.set('utm_campaign', 'social-referral')
    return url.href
}

export type SocialReferralListItem = {
    id: string
    organization: string
    user: number
    referee_state: Record<string, { first_event_sent?: boolean }>
    created_at: string
}

type PaginatedSocialReferrals = {
    count: number
    next: string | null
    previous: string | null
    results: SocialReferralListItem[]
}

export const referralsSceneLogic = kea([
    path(['scenes', 'referrals', 'referralsSceneLogic']),
    tabAwareScene(),
    connect(() => ({
        values: [organizationLogic, ['currentOrganizationId'], userLogic, ['user']],
    })),
    loaders(({ values }) => ({
        referrals: [
            [] as SocialReferralListItem[],
            {
                loadReferrals: async () => {
                    const orgId = values.currentOrganizationId
                    const data = await api.get<PaginatedSocialReferrals>(`api/organizations/${orgId}/social_referrals/`)
                    return data.results ?? []
                },
            },
        ],
    })),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.Referrals,
                    name: sceneConfigurations[Scene.Referrals].name,
                    iconType: sceneConfigurations[Scene.Referrals].iconType || 'link',
                },
            ],
        ],
        referralShareUrl: [
            (s) => [s.user],
            (user: UserType | null): string | null =>
                user?.distinct_id ? socialReferralSignupUrl(user.distinct_id) : null,
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadReferrals()
    }),
])
