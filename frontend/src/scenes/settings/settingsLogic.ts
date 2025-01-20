import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { Realm } from '~/types'

import type { settingsLogicType } from './settingsLogicType'
import { SETTINGS_MAP } from './SettingsMap'
import { Setting, SettingId, SettingLevelId, SettingSection, SettingSectionId, SettingsLogicProps } from './types'

export const settingsLogic = kea<settingsLogicType>([
    props({} as SettingsLogicProps),
    key((props) => props.logicKey ?? 'global'),
    path((key) => ['scenes', 'settings', 'settingsLogic', key]),
    connect({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            userLogic,
            ['hasAvailableFeature'],
            preflightLogic,
            ['preflight'],
            teamLogic,
            ['currentTeam'],
        ],
    }),

    actions({
        selectSection: (section: SettingSectionId, level: SettingLevelId) => ({ section, level }),
        selectLevel: (level: SettingLevelId) => ({ level }),
        selectSetting: (setting: SettingId) => ({ setting }),
        openCompactNavigation: true,
        closeCompactNavigation: true,
    }),

    reducers(({ props }) => ({
        selectedLevelRaw: [
            (props.settingLevelId ?? 'project') as SettingLevelId,
            {
                selectLevel: (_, { level }) => level,
                selectSection: (_, { level }) => level,
            },
        ],
        selectedSectionIdRaw: [
            (props.sectionId ?? null) as SettingSectionId | null,
            {
                selectLevel: () => null,
                selectSection: (_, { section }) => section,
            },
        ],
        selectedSettingRaw: [
            (props.settingId ?? null) as SettingId | null,
            {
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
        settingId: [
            () => [(_, props) => props],
            (props): SettingId | null => {
                return props.settingId || null
            },
        ],
        sections: [
            (s) => [s.doesMatchFlags, s.featureFlags],
            (doesMatchFlags, featureFlags): SettingSection[] => {
                const sections = SETTINGS_MAP.filter(doesMatchFlags)
                if (!featureFlags[FEATURE_FLAGS.ENVIRONMENTS]) {
                    return sections
                        .filter((section) => section.level !== 'project')
                        .map((section) => ({
                            ...section,
                            id: section.id.replace('environment-', 'project-') as SettingSectionId,
                            level: section.level === 'environment' ? 'project' : section.level,
                            settings: section.settings.map((setting) => ({
                                ...setting,
                                title: setting.title.replace('environment', 'project'),
                                id: setting.id.replace('environment-', 'project-') as SettingId,
                            })),
                        }))
                }
                return sections
            },
        ],
        selectedLevel: [
            (s) => [s.selectedLevelRaw, s.selectedSectionIdRaw, s.featureFlags],
            (selectedLevelRaw, selectedSectionIdRaw, featureFlags): SettingLevelId => {
                // As of middle of September 2024, `details` and `danger-zone` are the only sections present
                // at both Environment and Project levels. Others we want to redirect based on the feature flag.
                if (
                    !selectedSectionIdRaw ||
                    (!selectedSectionIdRaw.endsWith('-details') && !selectedSectionIdRaw.endsWith('-danger-zone'))
                ) {
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
        selectedSettingId: [
            (s) => [s.settings, s.settingId],
            (settings, settingId): Setting['id'] | null => {
                return settings.find((s) => s.id === settingId)?.id ?? null
            },
        ],
        settings: [
            (s) => [
                s.selectedLevel,
                s.selectedSectionId,
                s.sections,
                s.settingId,
                s.doesMatchFlags,
                s.preflight,
                s.currentTeam,
            ],
            (
                selectedLevel,
                selectedSectionId,
                sections,
                settingId,
                doesMatchFlags,
                preflight,
                currentTeam
            ): Setting[] => {
                let settings: Setting[] = []

                if (selectedSectionId) {
                    settings = sections.find((x) => x.id === selectedSectionId)?.settings || []
                } else {
                    settings = sections
                        .filter((section) => section.level === selectedLevel)
                        .reduce((acc, section) => [...acc, ...section.settings], [] as Setting[])
                }

                if (settingId) {
                    return settings.filter((x) => x.id === settingId)
                }

                return settings.filter((x) => {
                    if (!doesMatchFlags(x)) {
                        return false
                    }
                    if (x.hideOn?.includes(Realm.Cloud) && preflight?.cloud) {
                        return false
                    }
                    if (x.allowForTeam) {
                        return x.allowForTeam(currentTeam)
                    }
                    return true
                })
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
    }),

    listeners(({ values }) => ({
        async selectSetting({ setting }) {
            const url = urls.absolute(
                urls.currentProject(
                    urls.settings(values.selectedSectionId ?? values.selectedLevel, setting as SettingId)
                )
            )
            await copyToClipboard(url)
        },
    })),
])
