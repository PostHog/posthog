import FuseClass from 'fuse.js'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { organizationIntegrationsLogic } from 'scenes/settings/organization/organizationIntegrationsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { Realm } from '~/types'

import { SETTINGS_MAP } from './SettingsMap'
import type { settingsLogicType } from './settingsLogicType'
import { Setting, SettingId, SettingLevelId, SettingSection, SettingSectionId, SettingsLogicProps } from './types'

// Explicitly avoid "heat" matching "feature flags", but still allowing "heature" to match it
const FUSE_THRESHOLD = 0.2

// Helping kea-typegen navigate the exported default class for Fuse
export interface SettingsFuse extends FuseClass<Setting> {}
export interface SectionsFuse extends FuseClass<SettingSection> {}

export interface SearchIndexEntry {
    settingId: SettingId
    settingTitle: string
    sectionId: SettingSectionId
    sectionTitle: string
    level: SettingLevelId
    keywords: string
    description: string
}

export interface SearchResult {
    settingId: SettingId
    settingTitle: string
    sectionId: SettingSectionId
    sectionTitle: string
    level: SettingLevelId
}

export interface SearchResultGroup {
    sectionId: SettingSectionId
    sectionTitle: string
    level: SettingLevelId
    results: SearchResult[]
}

export interface GlobalSearchFuse extends FuseClass<SearchIndexEntry> {}

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
            organizationIntegrationsLogic,
            ['organizationIntegrations'],
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
        toggleGroupCollapse: (group: string) => ({ group }),
        loadSettingsAsOf: (at: string, scope?: string | string[]) => ({ at, scope }),
        navigateToSetting: (sectionId: SettingSectionId, settingId: SettingId) => ({ sectionId, settingId }),
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

        collapsedGroups: [
            {} as Record<string, boolean>,
            {
                toggleGroupCollapse: (state, { group }) => ({
                    ...state,
                    [group]: !state[group],
                }),
            },
        ],
    })),

    loaders(() => ({
        settingsSnapshot: [
            null as Record<string, any> | null,
            {
                loadSettingsAsOf: async ({ at, scope }: { at: string; scope?: string | string[] }) => {
                    const scopeArray = Array.isArray(scope)
                        ? scope.filter((s): s is string => !!s)
                        : scope
                          ? [scope]
                          : undefined
                    if (!at) {
                        lemonToast.warning('A timestamp is required to load settings at a point in time')
                        return {}
                    }
                    return await api.teamSettings.asOf(at, scopeArray)
                },
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        selectSection: () => {
            setTimeout(() => {
                const mainElement = document.querySelector('main')
                if (mainElement) {
                    mainElement.scrollTo({ top: 0, behavior: 'smooth' })
                }
            }, 100)
        },
        navigateToSetting: ({ sectionId, settingId }) => {
            const section = values.sections.find((s) => s.id === sectionId)
            if (section) {
                actions.selectSection(sectionId, section.level)
                actions.setSearchTerm('')
                setTimeout(() => {
                    const element = document.getElementById(settingId)
                    if (element) {
                        element.scrollIntoView({ behavior: 'smooth', block: 'start' })
                    }
                }, 200)
            }
        },
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
            (s) => [s.doesMatchFlags, s.isCloudOrDev, s.currentTeam, s.organizationIntegrations],
            (doesMatchFlags, isCloudOrDev, currentTeam, organizationIntegrations): SettingSection[] => {
                const sections = SETTINGS_MAP.filter(doesMatchFlags).filter((section) => {
                    if (section.hideSelfHost && !isCloudOrDev) {
                        return false
                    }
                    if (
                        section.id === 'organization-integrations' &&
                        (!organizationIntegrations || organizationIntegrations.length === 0)
                    ) {
                        return false
                    }

                    return true
                })

                // If there's no current team, hide project and environment sections entirely
                if (!currentTeam) {
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
                                typeof setting.title === 'string'
                                    ? setting.title.replace('environment', 'project')
                                    : setting.title,
                            id: setting.id.replace('environment-', 'project-') as SettingId,
                        })),
                    }))
            },
        ],
        selectedLevel: [
            (s) => [s.selectedLevelRaw, s.selectedSectionIdRaw, s.currentTeam],
            (selectedLevelRaw, selectedSectionIdRaw, currentTeam): SettingLevelId => {
                if (
                    !selectedSectionIdRaw ||
                    (!selectedSectionIdRaw.endsWith('-details') && !selectedSectionIdRaw.endsWith('-danger-zone'))
                ) {
                    // If there's no current team, default to organization settings
                    if (!currentTeam) {
                        return 'organization'
                    }
                    // Convert environment to project
                    return selectedLevelRaw === 'environment' ? 'project' : selectedLevelRaw
                }
                return selectedLevelRaw
            },
        ],
        selectedSectionId: [
            (s) => [s.selectedSectionIdRaw],
            (selectedSectionIdRaw): SettingSectionId | null => {
                if (!selectedSectionIdRaw) {
                    return null
                }
                // Convert environment sections to project sections
                if (!selectedSectionIdRaw.endsWith('-details') && !selectedSectionIdRaw.endsWith('-danger-zone')) {
                    return selectedSectionIdRaw.replace(/^environment/, 'project') as SettingSectionId
                }
                return selectedSectionIdRaw
            },
        ],
        defaultSectionId: [
            (s) => [s.sections, s.selectedLevel],
            (sections, selectedLevel): SettingSectionId | null => {
                const firstSection = sections.find((s) => s.level === selectedLevel)
                return firstSection?.id ?? null
            },
        ],
        selectedSection: [
            (s) => [s.sections, s.selectedSectionId, s.defaultSectionId],
            (sections, selectedSectionId, defaultSectionId): SettingSection | null => {
                const effectiveId = selectedSectionId ?? defaultSectionId
                return sections.find((x) => x.id === effectiveId) ?? null
            },
        ],
        settings: [
            (s) => [
                s.selectedLevel,
                s.selectedSectionId,
                s.defaultSectionId,
                s.sections,
                s.doesMatchFlags,
                s.preflight,
                s.currentTeam,
            ],
            (
                selectedLevel,
                selectedSectionId,
                defaultSectionId,
                sections,
                doesMatchFlags,
                preflight,
                currentTeam
            ): Setting[] => {
                const effectiveSectionId = selectedSectionId ?? defaultSectionId

                let settings: Setting[] = []

                if (effectiveSectionId) {
                    settings = sections.find((x) => x.id === effectiveSectionId)?.settings || []
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
                    if (x.hideWhenNoSection && !effectiveSectionId) {
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
                    threshold: FUSE_THRESHOLD,
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
                    threshold: FUSE_THRESHOLD,
                })
            },
        ],

        isSearching: [(s) => [s.searchTerm], (searchTerm: string): boolean => searchTerm.trim().length > 0],

        globalSearchIndex: [
            (s) => [s.sections, s.doesMatchFlags, s.preflight, s.currentTeam],
            (sections, doesMatchFlags, preflight, currentTeam): GlobalSearchFuse => {
                const entries: SearchIndexEntry[] = []

                for (const section of sections) {
                    const sectionTitle =
                        typeof section.title === 'string' ? section.title : section.id.replace(/[-]/g, ' ')

                    for (const setting of section.settings) {
                        if (!doesMatchFlags(setting)) {
                            continue
                        }
                        if (setting.hideOn?.includes(Realm.Cloud) && preflight?.cloud) {
                            continue
                        }
                        if (setting.allowForTeam && !setting.allowForTeam(currentTeam)) {
                            continue
                        }

                        const settingTitle =
                            typeof setting.title === 'string' ? setting.title : setting.id.replace(/[-]/g, ' ')

                        entries.push({
                            settingId: setting.id,
                            settingTitle,
                            sectionId: section.id,
                            sectionTitle,
                            level: section.level,
                            keywords: (setting.keywords ?? []).join(' '),
                            description:
                                setting.searchDescription ??
                                (typeof setting.description === 'string' ? setting.description : ''),
                        })
                    }
                }

                return new FuseClass(entries, {
                    keys: [
                        { name: 'settingTitle', weight: 2 },
                        { name: 'keywords', weight: 1.5 },
                        { name: 'sectionTitle', weight: 1 },
                        { name: 'description', weight: 0.5 },
                        { name: 'settingId', weight: 0.5 },
                    ],
                    threshold: FUSE_THRESHOLD,
                    includeScore: true,
                })
            },
        ],

        searchResults: [
            (s) => [s.searchTerm, s.globalSearchIndex],
            (searchTerm, globalSearchIndex): SearchResultGroup[] => {
                if (!searchTerm.trim()) {
                    return []
                }

                const results = globalSearchIndex.search(searchTerm, { limit: 30 })
                const groupMap = new Map<SettingSectionId, SearchResultGroup>()

                for (const result of results) {
                    const { sectionId, sectionTitle, level, settingId, settingTitle } = result.item
                    let group = groupMap.get(sectionId)
                    if (!group) {
                        group = { sectionId, sectionTitle, level, results: [] }
                        groupMap.set(sectionId, group)
                    }
                    group.results.push({ settingId, settingTitle, sectionId, sectionTitle, level })
                }

                return Array.from(groupMap.values())
            },
        ],

        filteredLevels: [
            (s) => [s.levels, s.searchResults, s.isSearching],
            (levels, searchResults, isSearching): SettingLevelId[] => {
                if (!isSearching) {
                    return levels
                }

                const levelsWithResults = new Set(searchResults.map((g) => g.level))
                return levels.filter((level) => levelsWithResults.has(level))
            },
        ],

        filteredSections: [
            (s) => [s.sections, s.searchResults, s.isSearching],
            (sections, searchResults, isSearching): SettingSection[] => {
                if (!isSearching) {
                    return sections
                }

                const sectionIds = new Set(searchResults.map((g) => g.sectionId))
                return sections.filter((section) => sectionIds.has(section.id))
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
