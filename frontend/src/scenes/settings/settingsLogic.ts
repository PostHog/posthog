import FuseClass from 'fuse.js'
import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { Realm } from '~/types'

import { SETTINGS_MAP } from './SettingsMap'
import type { settingsLogicType } from './settingsLogicType'
import { Setting, SettingId, SettingLevelId, SettingSection, SettingSectionId, SettingsLogicProps } from './types'

// Helping kea-typegen navigate the exported default class for Fuse
export interface SettingsFuse extends FuseClass<Setting> {}
export interface SectionsFuse extends FuseClass<SettingSection> {}

const getSettingStringValue = (setting: Setting): string => {
    if (setting.searchTerm) {
        return setting.searchTerm
    }
    if (typeof setting.title === 'string') {
        return setting.title
    }
    return setting.id
}

const getSectionStringValue = (section: SettingSection): string => {
    if (section.searchValue) {
        return section.searchValue
    }
    if (typeof section.title === 'string') {
        return section.title
    }
    return section.id
}

export const settingsLogic = kea<settingsLogicType>([
    props({} as SettingsLogicProps),
    key((props) => props.logicKey ?? 'global'),
    path((key) => ['scenes', 'settings', 'settingsLogic', key]),
    connect(() => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            userLogic,
            ['hasAvailableFeature'],
            preflightLogic,
            ['preflight', 'isCloudOrDev'],
            teamLogic,
            ['currentTeam'],
        ],
    })),

    actions({
        selectLevel: (level: SettingLevelId) => ({ level }),
        selectSection: (section: SettingSectionId, level: SettingLevelId) => ({ section, level }),
        selectSetting: (setting: SettingId) => ({ setting }),
        openCompactNavigation: true,
        closeCompactNavigation: true,
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        toggleLevelCollapse: (level: SettingLevelId) => ({ level }),
    }),

    reducers(({ props }) => ({
        selectedLevelRaw: [
            props.settingLevelId ?? 'project',
            {
                selectLevel: (_, { level }) => level,
                selectSection: (_, { level }) => level,
            },
        ],
        selectedSectionIdRaw: [
            props.sectionId ?? null,
            {
                selectLevel: () => null,
                selectSection: (_, { section }) => section,
            },
        ],
        selectedSettingId: [
            props.settingId ?? null,
            {
                selectLevel: () => null,
                selectSection: () => null,
                selectSetting: (_, { setting }) => setting,
            },
        ],

        isCompactNavigationOpen: [
            false,
            {
                openCompactNavigation: () => true,
                closeCompactNavigation: () => false,
                selectLevel: () => false,
                selectSection: () => false,
                selectSetting: () => false,
            },
        ],

        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],

        collapsedLevels: [
            {} as Record<SettingLevelId, boolean>,
            {
                toggleLevelCollapse: (state, { level }) => ({
                    ...state,
                    [level]: !state[level],
                }),
                // Auto-expand when selecting a level
                selectLevel: (state, { level }) => ({
                    ...state,
                    [level]: false,
                }),
                // Auto-expand when selecting a section
                selectSection: (state, { level }) => ({
                    ...state,
                    [level]: false,
                }),
            },
        ],
    })),

    selectors({
        levels: [
            (s) => [s.sections],
            (sections): SettingLevelId[] => {
                return sections.reduce<SettingLevelId[]>((acc, section) => {
                    if (!acc.includes(section.level)) {
                        acc.push(section.level)
                    }
                    return acc
                }, [])
            },
        ],
        sections: [
            (s) => [s.doesMatchFlags, s.featureFlags, s.isCloudOrDev, s.currentTeam],
            (doesMatchFlags, featureFlags, isCloudOrDev, currentTeam): SettingSection[] => {
                const sections = SETTINGS_MAP.filter(doesMatchFlags).filter((section) => {
                    if (section.hideSelfHost && !isCloudOrDev) {
                        return false
                    }

                    return true
                })

                // If there's no current team, hide project and environment sections entirely
                if (!currentTeam) {
                    return sections.filter((section) => section.level !== 'environment' && section.level !== 'project')
                }

                if (!featureFlags[FEATURE_FLAGS.ENVIRONMENTS]) {
                    return sections
                        .filter((section) => section.level !== 'project')
                        .map((section) => ({
                            ...section,
                            id: section.id.replace('environment-', 'project-') as SettingSectionId,
                            level: section.level === 'environment' ? 'project' : section.level,
                            settings: section.settings.map((setting) => ({
                                ...setting,
                                title:
                                    typeof setting.title === 'string'
                                        ? setting.title.replace('environment', 'project')
                                        : setting.title,
                                id: setting.id.replace('environment-', 'project-') as SettingId,
                            })),
                        }))
                }
                return sections
            },
        ],
        selectedLevel: [
            (s) => [s.selectedLevelRaw, s.selectedSectionIdRaw, s.featureFlags, s.currentTeam],
            (selectedLevelRaw, selectedSectionIdRaw, featureFlags, currentTeam): SettingLevelId => {
                // As of middle of September 2024, `details` and `danger-zone` are the only sections present
                // at both Environment and Project levels. Others we want to redirect based on the feature flag.
                if (
                    !selectedSectionIdRaw ||
                    (!selectedSectionIdRaw.endsWith('-details') && !selectedSectionIdRaw.endsWith('-danger-zone'))
                ) {
                    // If there's no current team, default to organization settings
                    if (!currentTeam) {
                        return 'organization'
                    }
                    if (featureFlags[FEATURE_FLAGS.ENVIRONMENTS]) {
                        return selectedLevelRaw === 'project' ? 'environment' : selectedLevelRaw
                    }
                    return selectedLevelRaw === 'environment' ? 'project' : selectedLevelRaw
                }
                return selectedLevelRaw
            },
        ],
        selectedSectionId: [
            (s) => [s.selectedSectionIdRaw, s.featureFlags],
            (selectedSectionIdRaw, featureFlags): SettingSectionId | null => {
                if (!selectedSectionIdRaw) {
                    return null
                }
                // As of middle of September 2024, `details` and `danger-zone` are the only sections present
                // at both Environment and Project levels. Others we want to redirect based on the feature flag.
                if (!selectedSectionIdRaw.endsWith('-details') && !selectedSectionIdRaw.endsWith('-danger-zone')) {
                    if (featureFlags[FEATURE_FLAGS.ENVIRONMENTS]) {
                        return selectedSectionIdRaw.replace(/^project/, 'environment') as SettingSectionId
                    }
                    return selectedSectionIdRaw.replace(/^environment/, 'project') as SettingSectionId
                }
                return selectedSectionIdRaw
            },
        ],
        selectedSection: [
            (s) => [s.sections, s.selectedSectionId],
            (sections, selectedSectionId): SettingSection | null => {
                return sections.find((x) => x.id === selectedSectionId) ?? null
            },
        ],
        settings: [
            (s) => [s.selectedLevel, s.selectedSectionId, s.sections, s.doesMatchFlags, s.preflight, s.currentTeam],
            (selectedLevel, selectedSectionId, sections, doesMatchFlags, preflight, currentTeam): Setting[] => {
                let settings: Setting[] = []

                if (selectedSectionId) {
                    settings = sections.find((x) => x.id === selectedSectionId)?.settings || []
                } else {
                    settings = sections
                        .filter((section) => section.level === selectedLevel)
                        .reduce((acc, section) => acc.concat(section.settings), [] as Setting[])
                }

                return settings.filter((x) => {
                    if (!doesMatchFlags(x)) {
                        return false
                    }
                    if (x.hideOn?.includes(Realm.Cloud) && preflight?.cloud) {
                        return false
                    }
                    if (x.hideWhenNoSection && !selectedSectionId) {
                        return false
                    }
                    if (x.allowForTeam) {
                        return x.allowForTeam(currentTeam)
                    }
                    return true
                })
            },
        ],
        selectedSetting: [
            (s) => [s.settings, s.selectedSettingId],
            (settings, selectedSettingId): Setting | null => {
                return settings.find((s) => s.id === selectedSettingId) ?? null
            },
        ],
        doesMatchFlags: [
            (s) => [s.featureFlags],
            (featureFlags) => {
                return (x: Pick<Setting, 'flag'>) => {
                    if (!x.flag) {
                        // No flag condition
                        return true
                    }
                    const flagsArray = Array.isArray(x.flag) ? x.flag : [x.flag]
                    for (const flagCondition of flagsArray) {
                        const flag = (
                            flagCondition.startsWith('!') ? flagCondition.slice(1) : flagCondition
                        ) as keyof typeof FEATURE_FLAGS
                        let isConditionMet = featureFlags[FEATURE_FLAGS[flag]]
                        if (flagCondition.startsWith('!')) {
                            isConditionMet = !isConditionMet // Negated flag condition (!-prefixed)
                        }
                        if (!isConditionMet) {
                            return false
                        }
                    }
                    return true
                }
            },
        ],

        settingsFuse: [
            (s) => [s.settings],
            (settings: Setting[]): SettingsFuse => {
                const settingsWithSearchValues = settings.map((setting) => ({
                    ...setting,
                    searchValue: getSettingStringValue(setting),
                }))

                return new FuseClass(settingsWithSearchValues || [], {
                    keys: ['searchValue', 'id'],
                    threshold: 0.3,
                })
            },
        ],

        sectionsFuse: [
            (s) => [s.sections],
            (sections: SettingSection[]): SectionsFuse => {
                const sectionsWithSearchValues = sections.map((section) => ({
                    ...section,
                    searchValue: getSectionStringValue(section),
                    settingsSearchValues: section.settings.map(getSettingStringValue).join(' '),
                }))

                return new FuseClass(sectionsWithSearchValues || [], {
                    keys: ['searchValue', 'settingsSearchValues', 'id'],
                    threshold: 0.3,
                })
            },
        ],

        filteredLevels: [
            (s) => [s.levels, s.sections, s.searchTerm, s.sectionsFuse, s.settingsFuse],
            (
                levels: SettingLevelId[],
                sections: SettingSection[],
                searchTerm: string,
                sectionsFuse: SectionsFuse
            ): SettingLevelId[] => {
                if (!searchTerm.trim()) {
                    return levels
                }

                return levels.filter((level: SettingLevelId) => {
                    // Check if level name matches
                    if (level.toLowerCase().includes(searchTerm.toLowerCase())) {
                        return true
                    }

                    // Check if any section in this level matches using FuseJS
                    const levelSections = sections.filter((section: SettingSection) => section.level === level)
                    const matchingSections = sectionsFuse.search(searchTerm)

                    return matchingSections.some((result) =>
                        levelSections.some((section) => section.id === result.item.id)
                    )
                })
            },
        ],

        filteredSections: [
            (s) => [s.sections, s.searchTerm, s.sectionsFuse],
            (sections: SettingSection[], searchTerm: string, sectionsFuse: SectionsFuse): SettingSection[] => {
                if (!searchTerm.trim()) {
                    return sections
                }

                const matchingResults = sectionsFuse.search(searchTerm)
                const matchingIds = new Set(matchingResults.map((result) => result.item.id))

                return sections.filter((section) => matchingIds.has(section.id))
            },
        ],
    }),
    actionToUrl(() => ({
        selectSetting: ({ setting }) => {
            return [
                router.values.location.pathname,
                router.values.searchParams,
                { ...router.values.hashParams, selectedSetting: setting },
            ]
        },
    })),
    urlToAction(({ actions, values }) => ({
        ['*/replay/settings']: (_, __, hashParams) => {
            const { selectedSetting } = hashParams
            const selectedSettingId = selectedSetting as SettingId
            if (!selectedSettingId) {
                return
            }

            if (values.selectedSettingId !== selectedSettingId) {
                actions.selectSetting(selectedSettingId)
            }
        },
    })),
])
