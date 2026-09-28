import { OrganizationMembershipLevel } from 'lib/constants'

import type { TeamPublicType, TeamType } from '~/types'

export function cleanEmails(values: string[]): string[] {
    return Array.from(new Set(values.map((value) => value.trim().toLowerCase()).filter(Boolean)))
}

export function cleanDomains(values: string[]): string[] {
    return cleanEmails(values.map((value) => value.trim().replace(/^@/, '')))
}

export function canEditEmailMatching(team: TeamPublicType | TeamType | null): boolean {
    return !!team?.effective_membership_level && team.effective_membership_level >= OrganizationMembershipLevel.Admin
}
