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
import { Scene } from 'scenes/sceneTypes'

export const settingsSceneLogic = kea<settingsSceneLogicType>([
    path(['scenes', 'settings', 'settingsSceneLogic']),
    connect(() => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            settingsLogic({ logicKey: 'settingsScene' }),
            ['selectedLevel', 'selectedSectionId', 'sections', 'settings'],
        ],
        actions: [settingsLogic({ logicKey: 'settingsScene' }), ['selectLevel', 'selectSection', 'selectSetting']],
    })),

    selectors({
        breadcrumbs: [
            (s) => [s.selectedLevel, s.selectedSectionId, s.sections],
            (selectedLevel, selectedSectionId): Breadcrumb[] => [
                {
                    key: Scene.Settings,
                    name: `Settings`,
                    path: urls.settings('project'),
                },
                {
                    key: selectedSectionId || selectedLevel,
                    name: selectedSectionId
                        ? SettingsMap.find((x) => x.id === selectedSectionId)?.title
                        : capitalizeFirstLetter(selectedLevel),
                },
            ],
        ],
    }),

    urlToAction(({ actions, values }) => ({
        '/settings/:section': ({ section }) => {
            if (!section) {
                return
            }
            if (SettingLevelIds.includes(section as SettingLevelId)) {
                if (section !== values.selectedLevel) {
                    actions.selectLevel(section as SettingLevelId)
                }
            } else if (section !== values.selectedSectionId) {
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
