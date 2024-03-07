import { connect, kea, path, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { settingsLogic } from './settingsLogic'
import { SettingsMap } from './SettingsMap'
import type { settingsSceneLogicType } from './settingsSceneLogicType'
import { SettingLevelId, SettingLevelIds, SettingSectionId } from './types'

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
                    key: [Scene.Settings, selectedSectionId || selectedLevel],
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
            return [urls.settings(level), router.values.searchParams, router.values.hashParams]
        },
        selectSection({ section }) {
            return [urls.settings(section), router.values.searchParams, router.values.hashParams]
        },
        selectSetting({ setting }) {
            const url = urls.settings(values.selectedSectionId ?? values.selectedLevel, setting)

            return [url]
        },
    })),
])
