import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { SettingsSections } from './SettingsMap'

import type { settingsLogicType } from './settingsLogicType'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { actionToUrl, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'
import { Breadcrumb } from '~/types'
import { capitalizeFirstLetter, copyToClipboard } from 'lib/utils'
import { SettingSectionId, SettingLevelId, SettingSection, Setting, SettingLevelIds } from './types'

export const settingsLogic = kea<settingsLogicType>([
    path(['scenes', 'settings']),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),

    actions({
        selectSection: (section: SettingSectionId) => ({ section }),
        selectLevel: (level: SettingLevelId) => ({ level }),
        selectSetting: (setting: string) => ({ setting }),
    }),

    reducers({
        selectedLevel: [
            'project' as SettingLevelId,
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
        breadcrumbs: [
            (s) => [s.selectedLevel, s.selectedSectionId, s.sections],
            (selectedLevel, selectedSectionId): Breadcrumb[] => [
                {
                    name: `Settings`,
                    path: urls.settings('project'),
                },
                {
                    name: selectedSectionId
                        ? SettingsSections.find((x) => x.id === selectedSectionId)?.title
                        : capitalizeFirstLetter(selectedLevel),
                },
            ],
        ],
    }),

    urlToAction(({ actions }) => ({
        '/settings/:section': ({ section }, _, hashParams) => {
            // TODO: Should we ensure that a given setting always sets the correct section?

            if (SettingLevelIds.includes(section as SettingLevelId)) {
                actions.selectLevel(section as SettingLevelId)
            } else if (section) {
                actions.selectSection(section as SettingSectionId)
            }
        },
    })),

    actionToUrl(({ values }) => ({
        selectLevel({ level }) {
            return [urls.settings(level)]
        },
        selectSection({ section }) {
            return [urls.settings(section)]
        },
        selectSetting({ setting }) {
            const url = urls.settings(values.selectedSectionId ?? values.selectedLevel, setting)

            copyToClipboard(window.location.origin + url)

            return [url]
        },
    })),
])
