import { connect, kea, path, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { settingsLogic } from './settingsLogic'
import type { settingsSceneLogicType } from './settingsSceneLogicType'
import { SettingLevelId, SettingLevelIds, SettingSectionId } from './types'

export const settingsSceneLogic = kea<settingsSceneLogicType>([
    path(['scenes', 'settings', 'settingsSceneLogic']),
    connect(() => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            settingsLogic({ logicKey: 'settingsScene' }),
            ['selectedLevel', 'selectedSectionId', 'sections', 'settings', 'sections'],
        ],
        actions: [settingsLogic({ logicKey: 'settingsScene' }), ['selectLevel', 'selectSection', 'selectSetting']],
    })),

    selectors({
        breadcrumbs: [
            (s) => [s.selectedLevel, s.selectedSectionId, s.sections],
            (selectedLevel, selectedSectionId, sections): Breadcrumb[] => [
                {
                    key: Scene.Settings,
                    name: `Settings`,
                    path: urls.settings('project'),
                },
                {
                    key: [Scene.Settings, selectedSectionId || selectedLevel],
                    name: selectedSectionId
                        ? sections.find((x) => x.id === selectedSectionId)?.title
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
            // As of middle of September 2024, `details` and `danger-zone` are the only sections present
            // at both Environment and Project levels. Others we want to redirect based on the feature flag.
            if (!section.endsWith('-details') && !section.endsWith('-danger-zone')) {
                if (values.featureFlags[FEATURE_FLAGS.ENVIRONMENTS]) {
                    section = section.replace('project-', 'environment-')
                } else {
                    section = section.replace('environment-', 'project-')
                }
            }
            if (SettingLevelIds.includes(section as SettingLevelId)) {
                if (section !== values.selectedLevel) {
                    actions.selectLevel(section as SettingLevelId)
                }
            } else if (section !== values.selectedSectionId) {
                actions.selectSection(
                    section as SettingSectionId,
                    values.sections.find((x) => x.id === section)?.level || 'user'
                )
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
