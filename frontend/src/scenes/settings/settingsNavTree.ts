import { SettingLevelId, SettingSection } from './types'

export type SettingsNavItem =
    | { kind: 'section'; section: SettingSection; destructive: boolean }
    | { kind: 'group'; key: string; label: string; sections: SettingSection[] }

export interface SettingsNavLevel {
    level: SettingLevelId
    items: SettingsNavItem[]
}

export function settingsSectionLabel(section: SettingSection): string {
    return typeof section.title === 'string' ? section.title : section.id
}

function isDangerZone(section: SettingSection): boolean {
    return section.id.endsWith('-danger-zone')
}

export function settingsNavItems(level: SettingLevelId, sections: SettingSection[]): SettingsNavItem[] {
    const levelSections = sections.filter((section) => section.level === level)
    const otherSections = levelSections.filter((section) => !isDangerZone(section))

    const seenGroups = new Set<string>()
    const items = otherSections.flatMap((section): SettingsNavItem[] => {
        if (!section.group) {
            return [{ kind: 'section', section, destructive: false }]
        }
        if (seenGroups.has(section.group)) {
            return []
        }
        seenGroups.add(section.group)
        const groupSections = otherSections.filter((other) => other.group === section.group)
        // Only the Products group sorts by title, because the AI group lists PostHog AI first on purpose.
        if (section.group === 'Products') {
            groupSections.sort((a, b) => settingsSectionLabel(a).localeCompare(settingsSectionLabel(b)))
        }
        return [{ kind: 'group', key: `${level}-${section.group}`, label: section.group, sections: groupSections }]
    })

    return [
        ...items,
        ...levelSections
            .filter(isDangerZone)
            .map((section): SettingsNavItem => ({ kind: 'section', section, destructive: true })),
    ]
}

export function settingsNavTree(levels: SettingLevelId[], sections: SettingSection[]): SettingsNavLevel[] {
    return levels.map((level) => ({ level, items: settingsNavItems(level, sections) }))
}
