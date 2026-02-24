import { toSentenceCase } from 'lib/utils'

import { APIScopeObject, AccessControlLevel } from '~/types'

import { AccessControlRow, AccessControlsTab, ScopeType } from './types'

export function scopeTypeForAccessControlsTab(activeTab: AccessControlsTab): ScopeType {
    switch (activeTab) {
        case 'defaults':
            return 'default'
        case 'roles':
            return 'role'
        case 'members':
            return 'member'
    }
}

export function describeAccessControlLevel(
    level: AccessControlLevel | null | undefined,
    resourceKey: APIScopeObject
): string {
    if (level === null || level === undefined || level === AccessControlLevel.None) {
        return 'No access.'
    }

    if (resourceKey === 'project') {
        if (level === AccessControlLevel.Member) {
            return 'Project member access. Can use the project, but cannot manage project settings.'
        }
        if (level === AccessControlLevel.Admin) {
            return 'Project admin access. Full access, including managing project settings.'
        }
        if (level === AccessControlLevel.Viewer) {
            return 'Read-only access to the project.'
        }
    }

    if (level === AccessControlLevel.Viewer) {
        return 'View-only access. Cannot make changes.'
    }
    if (level === AccessControlLevel.Editor) {
        return 'Edit access. Can create and modify items.'
    }
    if (level === AccessControlLevel.Manager) {
        return 'Manage access. Can configure and manage items.'
    }

    return `${toSentenceCase(level)} access.`
}

export function humanizeAccessControlLevel(level: AccessControlLevel | null | undefined): string {
    if (level === null || level === undefined || level === AccessControlLevel.None) {
        return 'No access'
    }
    return toSentenceCase(level)
}

export function sortAccessControlRows(a: AccessControlRow, b: AccessControlRow): number {
    return a.role.name.localeCompare(b.role.name)
}

export function getScopeTypeNoun(scopeType: ScopeType): string {
    return scopeType === 'role' ? 'role' : 'member'
}

export function getIdForDefaultRow(): string {
    return 'default'
}

export function getIdForRoleRow(roleId: string): string {
    return `role:${roleId}`
}

export function getIdForMemberRow(memberId: string): string {
    return `member:${memberId}`
}
