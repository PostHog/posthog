import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import type { welcomeDialogLogicType } from './welcomeDialogLogicType'

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

export const welcomeDialogLogic = kea<welcomeDialogLogicType>([
    path(['scenes', 'welcome', 'welcomeDialogLogic']),

    connect(() => ({
        values: [userLogic, ['user']],
        actions: [userLogic, ['loadUser']],
    })),

    actions({
        dismissWelcome: true,
        closeDialog: true,
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
        // Close the dialog optimistically so it doesn't flash back while the
        // loadUser refetch is in flight.
        locallyClosed: [
            false,
            {
                dismissWelcome: () => true,
                closeDialog: () => true,
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
                        // Fail-soft — render a minimal welcome if the aggregation endpoint errors.
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
        // Only open for invitees (not the org creator) who haven't already dismissed it.
        shouldShowDialog: [
            (s) => [s.user, s.locallyClosed],
            (user, locallyClosed): boolean =>
                !!user && user.is_organization_first_user === false && !user.welcome_screen_seen_at && !locallyClosed,
        ],
    }),

    listeners(({ actions, values }) => ({
        loadWelcomeDataSuccess: ({ welcomeData }) => {
            if (!values.shouldShowDialog) {
                return
            }
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
            // Refresh user so welcome_screen_seen_at persists for future sessions.
            actions.loadUser()
        },
        trackCardClick: ({ card, targetHref }) => {
            actions.markCardInteracted(card)
            posthog.capture('welcome_screen_card_clicked', {
                card,
                target_href: targetHref,
            })
        },
    })),

    // Watch shouldShowDialog and trigger the fetch when it transitions to true.
    // This handles the race where the dialog mounts before userLogic has loaded
    // the user, so afterMount alone would have skipped the fetch.
    subscriptions(({ actions, values }) => ({
        shouldShowDialog: (shouldShow: boolean, previous: boolean | undefined) => {
            if (shouldShow && !previous && values.welcomeData === EMPTY_PAYLOAD && !values.welcomeDataLoading) {
                actions.loadWelcomeData()
            }
        },
    })),
])
