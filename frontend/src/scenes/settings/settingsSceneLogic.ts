import { connect, kea, path, selectors } from 'kea'
import { SettingsMap } from './SettingsMap'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { actionToUrl, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'
import { Breadcrumb } from '~/types'
import { capitalizeFirstLetter } from 'lib/utils'
import { SettingSectionId, SettingLevelId, SettingLevelIds } from './types'

import type { settingsSceneLogicType } from './settingsSceneLogicType'
import { settingsLogic } from './settingsLogic'

export const settingsSceneLogic = kea<settingsSceneLogicType>([
    path(['scenes', 'settings', 'settingsSceneLogic']),
    connect(() => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            settingsLogic,
            ['selectedLevel', 'selectedSectionId', 'sections', 'settings'],
        ],
        actions: [settingsLogic, ['selectLevel', 'selectSection', 'selectSetting']],
    })),

    selectors({
        breadcrumbs: [
            (s) => [s.selectedLevel, s.selectedSectionId, s.sections],
            (selectedLevel, selectedSectionId): Breadcrumb[] => [
                {
                    name: `Settings`,
                    path: urls.settings('project'),
                },
                {
                    name: selectedSectionId
                        ? SettingsMap.find((x) => x.id === selectedSectionId)?.title
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

            return [url]
        },
    })),
])
