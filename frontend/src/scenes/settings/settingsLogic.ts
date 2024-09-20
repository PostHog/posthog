import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import type { settingsLogicType } from './settingsLogicType'
import { SettingsMap } from './SettingsMap'
import { Setting, SettingId, SettingLevelId, SettingSection, SettingSectionId, SettingsLogicProps } from './types'

export const settingsLogic = kea<settingsLogicType>([
    props({} as SettingsLogicProps),
    key((props) => props.logicKey ?? 'global'),
    path((key) => ['scenes', 'settings', 'settingsLogic', key]),
    connect({
        values: [featureFlagLogic, ['featureFlags'], userLogic, ['hasAvailableFeature']],
    }),

    actions({
        selectSection: (section: SettingSectionId) => ({ section }),
        selectLevel: (level: SettingLevelId) => ({ level }),
        selectSetting: (setting: string) => ({ setting }),
        openCompactNavigation: true,
        closeCompactNavigation: true,
    }),

    reducers(({ props }) => ({
        selectedLevel: [
            (props.settingLevelId ?? 'project') as SettingLevelId,
            {
                selectLevel: (_, { level }) => level,
                selectSection: (_, { section }) => SettingsMap.find((x) => x.id === section)?.level || 'user',
            },
        ],
        selectedSectionId: [
            (props.sectionId ?? null) as SettingSectionId | null,
            {
                selectLevel: () => null,
                selectSection: (_, { section }) => section,
            },
        ],

        isCompactNavigationOpen: [
            false,
            {
                openCompactNavigation: () => true,
                closeCompactNavigation: () => false,
                selectLevel: () => false,
                selectSection: () => false,
            },
        ],
    })),

    selectors({
        settingId: [
            () => [(_, props) => props],
            (props): SettingId | null => {
                return props.settingId || null
            },
        ],
        sections: [
            (s) => [s.featureFlags],
            (featureFlags): SettingSection[] => {
                return SettingsMap.filter((x) => {
                    const isFlagConditionMet = !x.flag
                        ? true // No flag condition
                        : x.flag.startsWith('!')
                        ? !featureFlags[FEATURE_FLAGS[x.flag.slice(1)]] // Negated flag condition (!-prefixed)
                        : featureFlags[FEATURE_FLAGS[x.flag]] // Regular flag condition
                    return isFlagConditionMet
                })
            },
        ],
        selectedSection: [
            (s) => [s.sections, s.selectedSectionId],
            (sections, selectedSectionId): SettingSection | null => {
                return sections.find((x) => x.id === selectedSectionId) ?? null
            },
        ],
        settings: [
            (s) => [
                s.selectedLevel,
                s.selectedSectionId,
                s.sections,
                s.settingId,
                s.featureFlags,
                s.hasAvailableFeature,
            ],
            (selectedLevel, selectedSectionId, sections, settingId, featureFlags, hasAvailableFeature): Setting[] => {
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
                    const isFlagConditionMet = !x.flag
                        ? true // No flag condition
                        : x.flag.startsWith('!')
                        ? !featureFlags[FEATURE_FLAGS[x.flag.slice(1)]] // Negated flag condition (!-prefixed)
                        : featureFlags[FEATURE_FLAGS[x.flag]] // Regular flag condition
                    if (x.flag && x.features) {
                        return x.features.some((feat) => hasAvailableFeature(feat)) || isFlagConditionMet
                    } else if (x.features) {
                        return x.features.some((feat) => hasAvailableFeature(feat))
                    } else if (x.flag) {
                        return isFlagConditionMet
                    }

                    return true
                })
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
