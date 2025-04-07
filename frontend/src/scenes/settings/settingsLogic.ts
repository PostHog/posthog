import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { Realm } from '~/types'

import type { settingsLogicType } from './settingsLogicType'
import { SETTINGS_MAP } from './SettingsMap'
import { Setting, SettingId, SettingLevelId, SettingSection, SettingSectionId, SettingsLogicProps } from './types'

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
    }),

    reducers(({ props }) => ({
        selectedLevel: [
            props.settingLevelId ?? 'project',
            {
                selectLevel: (_, { level }) => level,
                selectSection: (_, { level }) => level,
            },
        ],
        selectedSectionId: [
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
            (s) => [s.doesMatchFlags, s.isCloudOrDev],
            (doesMatchFlags, isCloudOrDev): SettingSection[] => {
                const sections = SETTINGS_MAP.filter(doesMatchFlags).filter((section) => {
                    if (section.hideSelfHost && !isCloudOrDev) {
                        return false
                    }

                    return true
                })
                return sections
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
                        .reduce((acc, section) => [...acc, ...section.settings], [] as Setting[])
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
    }),
])
