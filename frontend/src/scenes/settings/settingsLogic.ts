import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { Setting, SettingLevel, SettingSection, SettingSectionId, SettingsSections } from './SettingsMap'

import type { settingsLogicType } from './settingsLogicType'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export const settingsLogic = kea<settingsLogicType>([
    path(['scenes', 'settings']),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),

    actions({
        selectSection: (section: SettingSectionId) => ({ section }),
        selectLevel: (level: SettingLevel) => ({ level }),
    }),

    reducers({
        selectedLevel: [
            'project' as SettingLevel,
            {
                selectLevel: (_, { level }) => level,
                selectSection: (_, { section }) => SettingsSections.find((x) => x.id === section)?.level || 'user',
            },
        ],
        selectedSectionId: [
            null as SettingSectionId | null,
            {
                selectLevel: () => null,
                selectSection: (_, { section }) => section,
            },
        ],
    }),

    selectors({
        sections: [
            (s) => [s.featureFlags],
            (featureFlags): SettingSection[] => {
                return SettingsSections.filter((x) => (x.flag ? featureFlags[FEATURE_FLAGS[x.flag]] : true))
            },
        ],
        settings: [
            (s) => [s.selectedLevel, s.selectedSectionId, s.sections],
            (selectedLevel, selectedSectionId, sections): Setting[] => {
                let settings: Setting[] = []

                if (!selectedSectionId) {
                    settings = sections
                        .filter((section) => section.level === selectedLevel)
                        .reduce((acc, section) => [...acc, ...section.settings], [] as Setting[])
                } else {
                    settings = sections.find((x) => x.id === selectedSectionId)?.settings || []
                }

                return settings
            },
        ],
    }),
])
