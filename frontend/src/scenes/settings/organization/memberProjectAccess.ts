import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import type { MemberProjectAccessEntryApi } from 'products/access_control/frontend/generated/api.schemas'

/** The projects a member can reach, in the order the API returns them (by project name). */
export function accessibleProjects(entries: MemberProjectAccessEntryApi[]): MemberProjectAccessEntryApi[] {
    return entries.filter((entry) => entry.access_level !== 'none')
}

export function describeProjectAccessSource(entry: MemberProjectAccessEntryApi): string {
    const resolved = entry.resolved
    if (!resolved) {
        return 'No rule applies'
    }
    switch (resolved.source) {
        case 'org_admin':
            return 'Organization admins always have full access'
        case 'creator':
            return 'Created this project'
        case 'system_default':
            return 'No access rules set'
    }
    switch (resolved.source_subject) {
        case 'member':
            return 'Set for this member'
        case 'role':
            return resolved.subject_name ? `Based on role ${resolved.subject_name}` : 'Based on role permissions'
        case 'default':
            return 'Based on project default permissions'
    }
    return 'No rule applies'
}

/**
 * The access control page of the rule that decided this entry: the project defaults, the role's
 * detail, or the member's detail. Null when a bypass decided, since there is no rule to manage.
 */
export function projectAccessSourceUrl(entry: MemberProjectAccessEntryApi, membershipId: string): string | null {
    const resolved = entry.resolved
    if (!resolved || resolved.source === 'org_admin' || resolved.source === 'creator') {
        return null
    }
    let params: Record<string, string>
    if (resolved.source_subject === 'role' && entry.subject_id) {
        params = { access_tab: 'roles', access_role_id: entry.subject_id }
    } else if (resolved.source_subject === 'member') {
        params = { access_tab: 'members', access_member_id: membershipId }
    } else {
        params = { access_tab: 'defaults' }
    }
    return urls.project(entry.team_id, combineUrl(urls.settings('environment-access-control'), params).url)
}
