import { connect, kea, listeners, path, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { capitalizeFirstLetter } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { ActivityScope, Breadcrumb } from '~/types'

import { settingsLogic } from './settingsLogic'
import type { settingsSceneLogicType } from './settingsSceneLogicType'
import { SettingId, SettingLevelId, SettingLevelIds, SettingSectionId } from './types'

export const settingsSceneLogic = kea<settingsSceneLogicType>([
    path(['scenes', 'settings', 'settingsSceneLogic']),
    connect(() => ({
        values: [
            settingsLogic({ logicKey: 'settingsScene' }),
            ['selectedLevel', 'selectedSectionId', 'selectedSection', 'sections', 'settings'],
        ],
        actions: [settingsLogic({ logicKey: 'settingsScene' }), ['selectLevel', 'selectSection', 'selectSetting']],
    })),

    selectors({
        breadcrumbs: [
            (s) => [s.selectedLevel, s.selectedSectionId, s.selectedSection],
            (selectedLevel, selectedSectionId, selectedSection): Breadcrumb[] => {
                const sectionName = selectedSection?.title ?? capitalizeFirstLetter(selectedLevel)

                return [
                    {
                        key: Scene.Settings,
                        name: sectionName ? `Settings - ${sectionName}` : 'Settings',
                        path: urls.settings(selectedSectionId || selectedLevel),
                        iconType: 'settings',
                    },
                ]
            },
        ],

        [SIDE_PANEL_CONTEXT_KEY]: [
            (s) => [s.selectedSectionId],
            (selectedSectionId: SettingSectionId | null): SidePanelSceneContext | null => {
                if (selectedSectionId === 'user-api-keys') {
                    return {
                        activity_scope: ActivityScope.PERSONAL_API_KEY,
                    }
                }
                return null
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

    urlToAction(({ actions, values }) => ({
        '/settings/:section': ({ section }) => {
            if (!section) {
                return
            }

            // Redirect environment URLs to project URLs
            if (!section.endsWith('-details') && !section.endsWith('-danger-zone')) {
                section = section.replace(/^environment/, 'project')
            }

            if (SettingLevelIds.includes(section as SettingLevelId)) {
                // Redirect level-only URLs to the first section at that level
                const level = section as SettingLevelId
                const effectiveLevel = level === 'environment' ? 'project' : level
                const firstSection = values.sections.find((s) => s.level === effectiveLevel)
                if (firstSection) {
                    router.actions.replace(urls.settings(firstSection.id))
                } else {
                    actions.selectLevel(effectiveLevel)
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
        // Replacing history item instead of pushing, so that the environments<>project redirect doesn't affect history
        selectLevel({ level }) {
            return [urls.settings(level), router.values.searchParams, router.values.hashParams, { replace: true }]
        },
        selectSection({ section }) {
            return [urls.settings(section), router.values.searchParams, router.values.hashParams, { replace: true }]
        },
        selectSetting({ setting }) {
            return [
                urls.settings(values.selectedSectionId ?? values.selectedLevel),
                router.values.searchParams,
                { ...router.values.hashParams, setting },
                { replace: true },
            ]
        },
    })),
])
