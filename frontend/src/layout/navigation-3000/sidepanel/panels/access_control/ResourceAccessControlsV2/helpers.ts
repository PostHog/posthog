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
    const scopeOrder: Record<ScopeType, number> = { default: 0, role: 1, member: 2 }

    const scopeCmp = scopeOrder[a.scopeType] - scopeOrder[b.scopeType]
    if (scopeCmp !== 0) {
        return scopeCmp
    }

    const labelCmp = a.scopeLabel.localeCompare(b.scopeLabel)
    if (labelCmp !== 0) {
        return labelCmp
    }

    return a.resourceLabel.localeCompare(b.resourceLabel)
}

export function getScopeTypeNoun(scopeType: ScopeType): string {
    return scopeType === 'role' ? 'role' : 'member'
}
