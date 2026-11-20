import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { ADMIN_ONLY_SECTION_IDS } from '~/scenes/settings/sectionGating'
import { Setting, SettingId, SettingSection, SettingSectionId } from '~/scenes/settings/types'
import type { OrganizationType, Realm, TeamPublicType, TeamType } from '~/types'

/**
 * Kept apart from settingsLogic so consumers (e.g. command palette search) can gate on
 * setting flags without statically importing the full SettingsMap component graph.
 */
export const matchesFlagDefinition = (
    flagKey: Pick<Setting, 'flag'>['flag'],
    featureFlags: FeatureFlagsSet
): boolean => {
    // No flag condition
    if (!flagKey) {
        return true
    }

    const flagsArray = Array.isArray(flagKey) ? flagKey : [flagKey]
    for (const flagCondition of flagsArray) {
        // Tuple flag condition ([flag, value])
        if (Array.isArray(flagCondition)) {
            const [flag, value] = flagCondition
            const isConditionMet = featureFlags[FEATURE_FLAGS[flag]] === value
            if (!isConditionMet) {
                return false
            }
            // Negated flag condition (`!${FeatureFlagKey}`)
        } else if (flagCondition.startsWith('!')) {
            const flag = flagCondition.slice(1) as keyof typeof FEATURE_FLAGS
            const isConditionMet = !featureFlags[FEATURE_FLAGS[flag]]
            if (!isConditionMet) {
                return false
            }
            // Normal flag condition (FeatureFlagKey)
        } else {
            const flag = flagCondition as keyof typeof FEATURE_FLAGS
            const isConditionMet = !!featureFlags[FEATURE_FLAGS[flag]]
            if (!isConditionMet) {
                return false
            }
        }
    }
    return true
}

export interface SettingsVisibilityGates {
    featureFlags: FeatureFlagsSet
    isCloudOrDev: boolean | undefined
    realm: Realm | null | undefined
    currentTeam: TeamType | TeamPublicType | null
    currentOrganization: OrganizationType | null
    hasOrganizationIntegrations: boolean
    billingEntryUrl: string | null
    isAdminOrOwner: boolean | null
    isStaff: boolean
}

export const isSettingVisible = (setting: Setting, gates: SettingsVisibilityGates): boolean =>
    matchesFlagDefinition(setting.flag, gates.featureFlags) &&
    !(gates.realm && setting.hideOn?.includes(gates.realm)) &&
    (!setting.allowForTeam || setting.allowForTeam(gates.currentTeam)) &&
    (!setting.organizationAdminOnly || !!gates.isAdminOrOwner) &&
    (!setting.staffOnly || gates.isStaff)

export const visibleSettingsSections = (source: SettingSection[], gates: SettingsVisibilityGates): SettingSection[] => {
    const sections = source.filter(
        (section) =>
            matchesFlagDefinition(section.flag, gates.featureFlags) &&
            !(section.hideSelfHost && !gates.isCloudOrDev) &&
            // Explicit gates to avoid showing this in the sidebar when the use doesn't have access to it
            (section.id !== 'organization-integrations' || gates.hasOrganizationIntegrations) &&
            (section.id !== 'organization-billing' || !!gates.billingEntryUrl) &&
            (!ADMIN_ONLY_SECTION_IDS.includes(section.id) || !!gates.isAdminOrOwner)
    )

    // If there's no current organization, hide everything except user sections
    if (!gates.currentOrganization) {
        return sections.filter((section) => section.level === 'user')
    }

    // If there's no current team, hide project and environment sections entirely
    if (!gates.currentTeam) {
        return sections.filter((section) => section.level !== 'environment' && section.level !== 'project')
    }

    // Convert environment sections to project sections
    return sections
        .filter((section) => section.level !== 'project')
        .map((section) => ({
            ...section,
            id: section.id.replace('environment-', 'project-') as SettingSectionId,
            level: section.level === 'environment' ? 'project' : section.level,
            settings: section.settings.map((setting) => ({
                ...setting,
                title:
                    typeof setting.title === 'string' ? setting.title.replace('environment', 'project') : setting.title,
                id: setting.id.replace('environment-', 'project-') as SettingId,
            })),
        }))
        .filter(
            (section) =>
                section.to ||
                section.settings.length === 0 ||
                section.settings.some((setting) => isSettingVisible(setting, gates))
        )
}
