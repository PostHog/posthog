import { toSentenceCase } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import type { SettingSection, SettingSectionId } from '~/scenes/settings/types'

import { SearchItem } from './searchItems'

/**
 * Lean projection of SETTINGS_MAP for search. The full map statically imports every
 * settings component (the whole configuration UI graph), so it is loaded dynamically
 * on mount and only the searchable metadata is kept.
 */
export interface SettingsSectionSummary {
    id: SettingSection['id']
    level: SettingSection['level']
    titleString: string | null
    hideFromNavigation?: boolean
    flag?: SettingSection['flag']
    to?: string
    keywords?: string[]
    settings: {
        keywords: string[]
        description: string | null
        flag?: SettingSection['flag']
    }[]
}

export interface SettingsGates {
    isFlagEnabled: (flag: SettingSection['flag']) => boolean
    hasOrganizationIntegrations: boolean
    billingEntryUrl: string | null
}

export const sentenceCaseId = (id: string): string => toSentenceCase(id.replace(/-/g, ' '))

// Sections hidden from navigation are only reachable from their product's own configuration page.
// Integrations and billing mirror the sidebar gates. billingEntryUrl is null when the user has no
// billing access, and for view-only members it points at Usage, which keeps them off the admin-only
// Overview and the restricted state it renders first.
const isSectionShown = (section: SettingsSectionSummary, gates: SettingsGates): boolean =>
    !section.hideFromNavigation &&
    gates.isFlagEnabled(section.flag) &&
    (section.id !== 'organization-integrations' || gates.hasOrganizationIntegrations) &&
    (section.id !== 'organization-billing' || !!gates.billingEntryUrl)

const toSettingsSearchItem = (section: SettingsSectionSummary, gates: SettingsGates): SearchItem => {
    // Environment sections show as project sections.
    const level = section.level === 'environment' ? 'project' : section.level
    const sectionId = section.id.replace(/^environment-/, 'project-') as SettingSectionId
    const displayName = section.titleString ?? sentenceCaseId(section.id)
    const parentName = `${toSentenceCase(level)} settings`
    const settings = section.settings.filter((setting) => gates.isFlagEnabled(setting.flag))
    return {
        id: `settings-${sectionId}`,
        name: displayName,
        displayName,
        parentName,
        category: 'settings',
        href:
            (section.id === 'organization-billing' && gates.billingEntryUrl) || section.to || urls.settings(sectionId),
        itemType: 'settings',
        searchKeywords: [
            parentName,
            `${parentName} ${displayName}`,
            ...(section.keywords ?? []),
            ...settings.flatMap((setting) => setting.keywords),
        ],
        hiddenSearchText: settings.flatMap((setting) => setting.description ?? []).join(' '),
        record: { type: 'settings', level, sectionId },
    }
}

export const settingsSearchItems = (sections: SettingsSectionSummary[], gates: SettingsGates): SearchItem[] => {
    const items = new Map<string, SearchItem>()
    for (const section of sections) {
        if (!isSectionShown(section, gates)) {
            continue
        }
        const item = toSettingsSearchItem(section, gates)
        if (!items.has(item.id)) {
            items.set(item.id, item)
        }
    }
    return [...items.values()]
}
