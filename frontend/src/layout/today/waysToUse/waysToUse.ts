import { OrganizationMembershipLevel } from 'lib/constants'
import type {
    WelcomePopularDashboard,
    WelcomeRecentActivity,
    WelcomeTeamMember,
} from 'scenes/welcome/welcomeDialogLogic'

import type { IntegrationType, UserType } from '~/types'

export const WAYS_TO_USE_SEEN_KEY = 'today-ways-to-use'

export const WAYS_TO_USE_PARAM = 'ways_to_use'

export const SLACK_DOCS_URL = 'https://posthog.com/docs/libraries/slack'

const NEWCOMER_WINDOW_MS = 14 * 24 * 60 * 60 * 1000

export type WaysToUseSurface = 'chat' | 'slack' | 'mcp' | 'team_work' | 'members' | 'product_docs'

export type WaysToUseStep = 'team' | 'surfaces'

export interface WaysToUseTeamWorkItem {
    url: string
    name: string
    type: string
    detail: string
}

const MAX_TEAM_WORK_ITEMS = 4

export type WaysToUseCloseSource = 'get_started' | 'dismiss' | 'surface_link'

export type WaysToUseVariant = 'creator' | 'invitee'

export type WaysToUseSlackState = 'connected' | 'can_connect' | 'ask_admin'

export interface WaysToUseEligibility {
    todayRailEnabled: boolean
    onHome: boolean
    user: UserType | null
    blocked: boolean
    now: number
}

export function waysToUseSeenKey(user: UserType): string | null {
    const organizationId = user.organization?.id
    return organizationId ? `${WAYS_TO_USE_SEEN_KEY}:${organizationId}` : null
}

export function waysToUseVariant(user: UserType | null, isProvisionedUser: boolean): WaysToUseVariant {
    return user?.is_organization_first_user === false || isProvisionedUser ? 'invitee' : 'creator'
}

export function parseVariantParam(value: unknown): WaysToUseVariant | null {
    return value === 'creator' || value === 'invitee' ? value : null
}

export function waysToUseSlackState(
    integrations: IntegrationType[],
    teamMembershipLevel: OrganizationMembershipLevel | null | undefined
): WaysToUseSlackState {
    if (integrations.some((integration) => integration.kind === 'slack')) {
        return 'connected'
    }
    return (teamMembershipLevel ?? OrganizationMembershipLevel.Member) >= OrganizationMembershipLevel.Admin
        ? 'can_connect'
        : 'ask_admin'
}

function isNewMember(user: UserType, now: number): boolean {
    const joinedAt = Date.parse(user.organization?.membership_joined_at || user.date_joined)
    return !Number.isNaN(joinedAt) && now - joinedAt < NEWCOMER_WINDOW_MS
}

export function shouldOfferWaysToUse({ todayRailEnabled, onHome, user, blocked, now }: WaysToUseEligibility): boolean {
    if (!todayRailEnabled || !onHome || !user || blocked) {
        return false
    }
    const seenKey = waysToUseSeenKey(user)
    return !!seenKey && !user.has_seen_product_intro_for?.[seenKey] && isNewMember(user, now)
}

export function teamWorkItems(
    dashboards: WelcomePopularDashboard[],
    activity: WelcomeRecentActivity[]
): WaysToUseTeamWorkItem[] {
    const items: WaysToUseTeamWorkItem[] = dashboards.map((dashboard) => ({
        url: dashboard.url,
        name: dashboard.name,
        type: 'Dashboard',
        detail: 'Opened recently',
    }))
    for (const entry of activity) {
        if (entry.entity_url && !entry.type.endsWith('.deleted')) {
            items.push({
                url: entry.entity_url,
                name: entry.entity_name,
                type: entry.type,
                detail: `${entry.type.endsWith('.created') ? 'Created' : 'Updated'} by ${entry.actor_name.split(' ')[0]}`,
            })
        }
    }
    const seen = new Set<string>()
    return items
        .filter((item) => {
            if (seen.has(item.url)) {
                return false
            }
            seen.add(item.url)
            return true
        })
        .slice(0, MAX_TEAM_WORK_ITEMS)
}

export function waysToUseSteps(variant: WaysToUseVariant, hasTeamContent: boolean): WaysToUseStep[] {
    return variant === 'invitee' && hasTeamContent ? ['team', 'surfaces'] : ['surfaces']
}

const listFormat = new Intl.ListFormat('en', { style: 'long', type: 'conjunction' })

export function teammatesSummary(members: Pick<WelcomeTeamMember, 'name' | 'email' | 'last_active'>[]): string {
    const firstName = (member: Pick<WelcomeTeamMember, 'name' | 'email'>): string =>
        (member.name || member.email).split(' ')[0]
    const activeToday = members.filter((member) => member.last_active === 'today')
    if (activeToday.length === 1) {
        return `${firstName(activeToday[0])} was active today.`
    }
    if (activeToday.length > 1) {
        return `${listFormat.format(activeToday.slice(0, 2).map(firstName))} were active today.`
    }
    return members.length > 1
        ? `${firstName(members[0])} and others work here.`
        : `${firstName(members[0])} works here.`
}

const TEAM_WORK_LABELS: Record<string, string> = {
    Dashboard: 'Dashboard',
    Insight: 'Insight',
    FeatureFlag: 'Feature flag',
    Experiment: 'Experiment',
    Survey: 'Survey',
    Notebook: 'Notebook',
}

export function teamWorkLabel(type: string): string {
    return TEAM_WORK_LABELS[type.split('.')[0]] ?? 'Update'
}
