import { isUnderPath } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { SettingLevelId, SettingLevelNames, SettingSectionId } from './types'

export type SettingsPaneLevel = Exclude<SettingLevelId, 'environment'>

export interface SettingsSectionScene {
    sectionId: SettingSectionId
    level: SettingsPaneLevel
    url: string
    /** Where the current navigation links the section. It keeps working, and still counts as the section. */
    legacyUrl?: string
}

export const SETTINGS_SECTION_SCENES: SettingsSectionScene[] = [
    { sectionId: 'environment-exports', level: 'project', url: urls.exports() },
    { sectionId: 'organization-billing', level: 'organization', url: urls.organizationBilling() },
    {
        sectionId: 'organization-legal-documents',
        level: 'organization',
        url: urls.organizationLegalDocuments(),
        legacyUrl: urls.legalDocuments(),
    },
    {
        sectionId: 'organization-startup-program',
        level: 'organization',
        url: urls.organizationStartups(),
        legacyUrl: urls.startups(),
    },
]

/** The section whose scene a path opens. Takes a path without the project prefix. */
export function settingsSectionSceneForPath(path: string): SettingsSectionScene | null {
    return (
        SETTINGS_SECTION_SCENES.find(
            ({ url, legacyUrl }) => isUnderPath(path, url) || (!!legacyUrl && isUnderPath(path, legacyUrl))
        ) ?? null
    )
}

/**
 * The page a section with its own scene opens at, or null for a section the settings page renders.
 * Takes a `/settings/:section` id, which can carry either the environment or the project prefix.
 */
export function settingsSectionScenePage(sectionId: string): string | null {
    const toProjectId = (id: string): string => id.replace(/^environment-/, 'project-')
    const scene = SETTINGS_SECTION_SCENES.find((s) => toProjectId(s.sectionId) === toProjectId(sectionId))
    return scene?.url ?? null
}

export function settingsSectionSceneScope(sectionId: SettingSectionId): string | undefined {
    const scene = SETTINGS_SECTION_SCENES.find((s) => s.sectionId === sectionId)
    return scene ? SettingLevelNames[scene.level] : undefined
}
