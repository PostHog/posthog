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

export type WelcomeLastActive = 'today' | 'this_week' | 'inactive' | 'never'

export interface WelcomeTeamMember {
    name: string
    email: string
    avatar: string | null
    role: string
    last_active: WelcomeLastActive
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
    docs_href?: string
    product_key?: string
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

// LocalStorage key used to suppress the dialog on subsequent visits after the user has dismissed it.
// Scoped per-user so dismissal doesn't leak across accounts on a shared browser.
const LOCAL_DISMISSED_KEY_PREFIX = 'posthog_welcome_dismissed:'
// SessionStorage key used to suppress the dialog for the remainder of a tab's session after
// the user clicks "I'll look around" — avoids re-opening on every project-home remount.
const SESSION_LOOKED_AROUND_KEY = 'posthog_welcome_looked_around'

function dismissedKey(userUuid: string | undefined): string | null {
    return userUuid ? `${LOCAL_DISMISSED_KEY_PREFIX}${userUuid}` : null
}

function rememberDismissed(userUuid: string | undefined): void {
    const key = dismissedKey(userUuid)
    if (typeof window === 'undefined' || !key) {
        return
    }
    try {
        window.localStorage.setItem(key, '1')
    } catch {
        // localStorage can be unavailable (privacy mode, etc.) — degrade gracefully.
    }
}

export function wasWelcomeDismissed(userUuid: string | undefined): boolean {
    return wasDismissed(userUuid)
}

function wasDismissed(userUuid: string | undefined): boolean {
    const key = dismissedKey(userUuid)
    if (typeof window === 'undefined' || !key) {
        return false
    }
    try {
        return window.localStorage.getItem(key) === '1'
    } catch {
        return false
    }
}

function rememberLookedAround(orgId: string | undefined): void {
    if (typeof window === 'undefined' || !orgId) {
        return
    }
    try {
        window.sessionStorage.setItem(SESSION_LOOKED_AROUND_KEY, orgId)
    } catch {
        // sessionStorage can be unavailable (privacy mode, etc.) — degrade gracefully.
    }
}

function wasLookedAround(orgId: string | undefined): boolean {
    if (typeof window === 'undefined' || !orgId) {
        return false
    }
    try {
        return window.sessionStorage.getItem(SESSION_LOOKED_AROUND_KEY) === orgId
    } catch {
        return false
    }
}

export const welcomeDialogLogic = kea<welcomeDialogLogicType>([
    path(['scenes', 'welcome', 'welcomeDialogLogic']),

    connect(() => ({
        values: [userLogic, ['user']],
    })),

    actions({
        dismissWelcome: true,
        closeDialog: true,
        resetForOrgChange: true,
        trackCardClick: (card: WelcomeCardKind, targetHref: string) => ({ card, targetHref }),
        markCardInteracted: (card: WelcomeCardKind) => ({ card }),
        markShown: true,
        setWelcomeDataError: (error: boolean) => ({ error }),
    }),

    reducers({
        shownAt: [
            null as number | null,
            {
                markShown: () => Date.now(),
                resetForOrgChange: () => null,
            },
        ],
        interactedCards: [
            {} as Record<WelcomeCardKind, boolean>,
            {
                markCardInteracted: (state, { card }) => ({ ...state, [card]: true }),
                resetForOrgChange: () => ({}) as Record<WelcomeCardKind, boolean>,
            },
        ],
        // Hide the dialog optimistically so it doesn't flash back during the loadUser refetch.
        locallyClosed: [
            false,
            {
                dismissWelcome: () => true,
                closeDialog: () => true,
                resetForOrgChange: () => false,
            },
        ],
        hasLoadedOnce: [
            false,
            {
                loadWelcomeDataSuccess: () => true,
                resetForOrgChange: () => false,
            },
        ],
        welcomeDataError: [
            false,
            {
                setWelcomeDataError: (_, { error }) => error,
                loadWelcomeData: () => false,
                resetForOrgChange: () => false,
            },
        ],
    }),

    loaders(({ actions }) => ({
        welcomeData: [
            EMPTY_PAYLOAD,
            {
                loadWelcomeData: async () => {
                    try {
                        return await api.get<WelcomePayload>('api/organizations/@current/welcome/')
                    } catch (error) {
                        console.warn('Failed to load welcome data', error)
                        actions.setWelcomeDataError(true)
                        return EMPTY_PAYLOAD
                    }
                },
            },
        ],
    })),

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
            (user, locallyClosed): boolean => {
                if (!user || user.is_organization_first_user !== false) {
                    return false
                }
                if (wasDismissed(user.uuid)) {
                    return false
                }
                if (locallyClosed) {
                    return false
                }
                // Also suppress if the user opted to look around earlier in this tab's session.
                return !wasLookedAround(user.organization?.id)
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        loadWelcomeDataSuccess: ({ welcomeData }) => {
            if (!values.shouldShowDialog || values.welcomeDataError) {
                return
            }
            if (!welcomeData.organization_name) {
                // Empty payload = backend error that was caught and returned EMPTY_PAYLOAD.
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
        closeDialog: () => {
            // Persist "I'll look around" across remounts in the same tab.
            rememberLookedAround(values.user?.organization?.id)
        },
        dismissWelcome: () => {
            const interactedCount = Object.keys(values.interactedCards).length
            const timeOnScreen = values.shownAt ? Date.now() - values.shownAt : null
            rememberDismissed(values.user?.uuid)
            posthog.capture('welcome_screen_dismissed', {
                time_on_screen_ms: timeOnScreen,
                cards_interacted_with: interactedCount,
            })
        },
        trackCardClick: ({ card, targetHref }) => {
            actions.markCardInteracted(card)
            posthog.capture('welcome_screen_card_clicked', {
                card,
                target_href: targetHref,
            })
        },
    })),

    // Re-evaluate on user changes. Triggers the initial fetch once the user loads, and re-fetches
    // when the user switches current organization so we don't render stale data across orgs.
    subscriptions(({ actions, values }) => ({
        user: (nextUser, previousUser) => {
            const prevOrgId = previousUser?.organization?.id
            const nextOrgId = nextUser?.organization?.id
            if (prevOrgId && nextOrgId && prevOrgId !== nextOrgId) {
                actions.resetForOrgChange()
            }
        },
        shouldShowDialog: (shouldShow: boolean) => {
            if (shouldShow && !values.hasLoadedOnce && !values.welcomeDataLoading) {
                actions.loadWelcomeData()
            }
        },
    })),
])
