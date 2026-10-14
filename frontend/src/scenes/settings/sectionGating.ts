import { SettingSection, SettingSectionId, UnavailableSection } from '~/scenes/settings/types'

/**
 * Sections the settings navigation drops for everyone below organization admin. Kept here so the
 * navigation filter and the unavailable-section explanation stay in step.
 */
export const ADMIN_ONLY_SECTION_IDS: SettingSectionId[] = [
    'organization-legal-documents',
    'organization-access-resolution',
]

interface FindUnavailableSectionInput {
    /** Section the reader asked for, already mapped from environment to project. */
    sectionId: SettingSectionId | null
    /** Sections the reader can open. */
    visibleSections: SettingSection[]
    /** Every section the app defines, gated or not. */
    allSections: SettingSection[]
    /** False while the feature flags or the organization membership level are still on their way. */
    gatesResolved: boolean
    doesMatchFlags: (flagDefinition: Pick<SettingSection, 'flag'>) => boolean
    isAdminOrOwner: boolean | null
}

/**
 * Works out why a section the reader asked for is missing, so a deep link into a gated section can
 * explain itself instead of falling through to the generic not-found state.
 */
export const findUnavailableSection = ({
    sectionId,
    visibleSections,
    allSections,
    gatesResolved,
    doesMatchFlags,
    isAdminOrOwner,
}: FindUnavailableSectionInput): UnavailableSection | null => {
    if (!gatesResolved || !sectionId || visibleSections.some((section) => section.id === sectionId)) {
        return null
    }

    const definition = allSections.find(
        (section) => section.id === sectionId || section.id.replace(/^environment/, 'project') === sectionId
    )
    if (!definition) {
        return null
    }

    const reason = !doesMatchFlags(definition)
        ? 'not-enabled'
        : ADMIN_ONLY_SECTION_IDS.includes(definition.id) && !isAdminOrOwner
          ? 'admin-only'
          : null
    if (!reason) {
        return null
    }

    return {
        id: definition.id,
        title: definition.title,
        reason,
        fallback: definition.unavailableFallback ?? null,
    }
}
