import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import type { welcomeSceneLogicType } from './welcomeSceneLogicType'

export interface WelcomeInviter {
    name: string
    email: string
}

export interface WelcomeTeamMember {
    name: string
    email: string
    avatar: string | null
    role: string
    last_active: 'today' | 'this_week' | 'inactive'
}

export interface WelcomeRecentActivity {
    type: string
    actor_name: string
    entity_name: string
    entity_url: string | null
    timestamp: string
}

export interface WelcomePopularDashboard {
    id: number
    name: string
    description: string
    team_id: number
    url: string
}

export interface WelcomeSuggestedStep {
    label: string
    href: string
    reason: string
}

export interface WelcomePayload {
    organization_name: string
    inviter: WelcomeInviter | null
    team_members: WelcomeTeamMember[]
    recent_activity: WelcomeRecentActivity[]
    popular_dashboards: WelcomePopularDashboard[]
    products_in_use: string[]
    suggested_next_steps: WelcomeSuggestedStep[]
    is_organization_first_user: boolean
}

const EMPTY_PAYLOAD: WelcomePayload = {
    organization_name: '',
    inviter: null,
    team_members: [],
    recent_activity: [],
    popular_dashboards: [],
    products_in_use: [],
    suggested_next_steps: [],
    is_organization_first_user: false,
}

export type WelcomeCardKind = 'members' | 'activity' | 'dashboards' | 'products' | 'next_steps'

export const welcomeSceneLogic = kea<welcomeSceneLogicType>([
    path(['scenes', 'welcome', 'welcomeSceneLogic']),

    connect(() => ({
        values: [userLogic, ['user']],
        actions: [userLogic, ['loadUser']],
    })),

    actions({
        dismissWelcome: true,
        trackCardClick: (card: WelcomeCardKind, targetHref: string) => ({ card, targetHref }),
        markCardInteracted: (card: WelcomeCardKind) => ({ card }),
        markShown: true,
    }),

    reducers({
        shownAt: [
            null as number | null,
            {
                markShown: () => Date.now(),
            },
        ],
        interactedCards: [
            {} as Record<WelcomeCardKind, boolean>,
            {
                markCardInteracted: (state, { card }) => ({ ...state, [card]: true }),
            },
        ],
        // Local flag so sceneLogic stops redirecting back to /welcome during the
        // window between the dismiss POST and the user refetch landing.
        dismissedLocally: [
            false,
            {
                dismissWelcome: () => true,
            },
        ],
    }),

    loaders({
        welcomeData: [
            EMPTY_PAYLOAD,
            {
                loadWelcomeData: async () => {
                    try {
                        return await api.get<WelcomePayload>('api/organizations/@current/welcome/')
                    } catch (error) {
                        // Fail-soft — the scene should always render a minimal welcome even if the aggregation endpoint errors.
                        console.warn('Failed to load welcome data', error)
                        return EMPTY_PAYLOAD
                    }
                },
            },
        ],
    }),

    selectors({
        inviter: [(s) => [s.welcomeData], (data): WelcomeInviter | null => data.inviter],
        teamMembers: [(s) => [s.welcomeData], (data): WelcomeTeamMember[] => data.team_members],
        recentActivity: [(s) => [s.welcomeData], (data): WelcomeRecentActivity[] => data.recent_activity],
        popularDashboards: [(s) => [s.welcomeData], (data): WelcomePopularDashboard[] => data.popular_dashboards],
        productsInUse: [(s) => [s.welcomeData], (data): string[] => data.products_in_use],
        suggestedNextSteps: [(s) => [s.welcomeData], (data): WelcomeSuggestedStep[] => data.suggested_next_steps],
        organizationName: [
            (s) => [s.welcomeData, s.user],
            (data, user): string => data.organization_name || user?.organization?.name || '',
        ],
        primaryCtaHref: [
            (s) => [s.popularDashboards],
            (popularDashboards): string => popularDashboards[0]?.url ?? urls.default(),
        ],
        primaryCtaLabel: [
            (s) => [s.popularDashboards],
            (popularDashboards): string =>
                popularDashboards.length > 0
                    ? `Take me to ${popularDashboards[0].name}`
                    : 'Take me to the project home',
        ],
    }),

    listeners(({ actions, values }) => ({
        loadWelcomeDataSuccess: ({ welcomeData }) => {
            actions.markShown()
            posthog.capture('welcome_screen_shown', {
                org_id: values.user?.organization?.id,
                num_team_members: welcomeData.team_members.length,
                products_in_use: welcomeData.products_in_use,
                had_recent_activity: welcomeData.recent_activity.length > 0,
                from_invite_type: welcomeData.inviter ? 'invite' : 'unknown',
            })
        },
        dismissWelcome: async () => {
            const interactedCards = Object.keys(values.interactedCards).length
            const timeOnScreen = values.shownAt ? Date.now() - values.shownAt : null
            posthog.capture('welcome_screen_dismissed', {
                time_on_screen_ms: timeOnScreen,
                cards_interacted_with: interactedCards,
            })
            try {
                await api.create('api/users/@me/welcome_screen/dismiss/')
            } catch (error) {
                console.warn('Failed to dismiss welcome screen', error)
            }
            // Refresh the user so welcome_screen_seen_at reflects the new state.
            actions.loadUser()
            router.actions.push(values.primaryCtaHref)
        },
        trackCardClick: ({ card, targetHref }) => {
            actions.markCardInteracted(card)
            posthog.capture('welcome_screen_card_clicked', {
                card,
                target_href: targetHref,
            })
        },
    })),

    afterMount(({ actions }) => {
        actions.loadWelcomeData()
    }),
])
