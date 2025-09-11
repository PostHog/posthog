import { PluginsAccessLevel } from 'lib/constants'

import { OrganizationType } from '../../types'

export function canGloballyManagePlugins(organization: OrganizationType | null | undefined): boolean {
    if (!organization) {
        return false
    }
    return organization.plugins_access_level >= PluginsAccessLevel.Root
}

export function canInstallPlugins(
    organization: OrganizationType | null | undefined,
    specificOrganizationId?: string
): boolean {
    if (!organization) {
        return false
    }
    if (specificOrganizationId && organization.id !== specificOrganizationId) {
        return false
    }
    return organization.plugins_access_level >= PluginsAccessLevel.Install
}

export function canViewPlugins(organization: OrganizationType | null | undefined): boolean {
    if (!organization) {
        return false
    }
    return organization.plugins_access_level > PluginsAccessLevel.None
}

export function canConfigurePlugins(organization: OrganizationType | null | undefined): boolean {
    if (!organization) {
        return false
    }
    return organization.plugins_access_level >= PluginsAccessLevel.Config
}
