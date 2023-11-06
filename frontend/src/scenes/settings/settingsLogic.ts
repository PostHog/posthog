import { actions, kea, path, reducers, selectors } from 'kea'
import { Setting, SettingLevel, SettingSectionId, SettingsSections } from './SettingsMap'

import type { settingsLogicType } from './settingsLogicType'

export const settingsLogic = kea<settingsLogicType>([
    path(['scenes', 'settings']),

    actions({
        selectSection: (section: SettingSectionId) => ({ section }),
        selectLevel: (level: SettingLevel) => ({ level }),
    }),

    reducers({
        selectedLevel: [
            'user' as SettingLevel,
            {
                selectLevel: (_, { level }) => level,
            },
        ],
        selectedSectionId: [
            null as SettingSectionId | null,
            {
                selectSection: (_, { section }) => section,
            },
        ],
    }),

    selectors({
        settings: [
            (s) => [s.selectedLevel, s.selectedSectionId],
            (selectedLevel, selectedSectionId): Setting[] => {
                if (!selectedSectionId) {
                    console.log(
                        'wat',
                        SettingsSections.filter((section) => section.level === selectedLevel)
                    )
                    return SettingsSections.filter((section) => section.level === selectedLevel).reduce(
                        (acc, section) => [...acc, ...section.settings],
                        [] as Setting[]
                    )
                }

                return SettingsSections.find((x) => x.id === selectedSectionId)?.settings || []
            },
        ],
    }),
])
