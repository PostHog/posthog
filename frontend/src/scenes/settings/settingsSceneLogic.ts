import { connect, kea, listeners, path, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { Scene } from 'scenes/sceneTypes'
import type { Params } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation/sidepanel/types'
import { ActivityScope, Breadcrumb } from '~/types'

import { settingsLogic } from './settingsLogic'
import type { settingsSceneLogicType } from './settingsSceneLogicType'
import { SettingId, SettingLevelId, SettingLevelIds, SettingSectionId } from './types'

const AI_OBSERVABILITY_SETTINGS_SECTION: SettingSectionId = 'project-ai-observability'
const AI_OBSERVABILITY_BYOK_SETTING: SettingId = 'ai-observability-byok'
const LEGACY_LLM_ANALYTICS_BYOK_SETTING = 'llm-analytics-byok'

const LEGACY_SETTINGS_SECTIONS: Record<string, SettingSectionId> = {
    'environment-llm-analytics': AI_OBSERVABILITY_SETTINGS_SECTION,
    'project-llm-analytics': AI_OBSERVABILITY_SETTINGS_SECTION,
}

const hasHashParam = (hashParams: Params, key: string): boolean => Object.prototype.hasOwnProperty.call(hashParams, key)

const canonicalSettingsSection = (section: string): string => {
    if (LEGACY_SETTINGS_SECTIONS[section]) {
        return LEGACY_SETTINGS_SECTIONS[section]
    }

    if (section.startsWith('environment') && !section.endsWith('-details') && !section.endsWith('-danger-zone')) {
        return section.replace(/^environment/, 'project')
    }

    return section
}

const canonicalSettingsHashParams = (hashParams: Params): [Params, boolean] => {
    const nextHashParams = { ...hashParams }
    let changed = false

    if (hasHashParam(nextHashParams, LEGACY_LLM_ANALYTICS_BYOK_SETTING)) {
        delete nextHashParams[LEGACY_LLM_ANALYTICS_BYOK_SETTING]
        nextHashParams[AI_OBSERVABILITY_BYOK_SETTING] = null
        changed = true
    }

    if (nextHashParams.setting === LEGACY_LLM_ANALYTICS_BYOK_SETTING) {
        nextHashParams.setting = AI_OBSERVABILITY_BYOK_SETTING
        nextHashParams[AI_OBSERVABILITY_BYOK_SETTING] = null
        changed = true
    }

    if (nextHashParams.selectedSetting === LEGACY_LLM_ANALYTICS_BYOK_SETTING) {
        nextHashParams.selectedSetting = AI_OBSERVABILITY_BYOK_SETTING
        nextHashParams[AI_OBSERVABILITY_BYOK_SETTING] = null
        changed = true
    }

    return [nextHashParams, changed]
}

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
                if (selectedSectionId === 'user-connected-apps') {
                    return {
                        activity_scope: ActivityScope.OAUTH_APPLICATION,
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

            const canonicalSection = canonicalSettingsSection(section)
            const [hashParams, didCanonicalizeHashParams] = canonicalSettingsHashParams(router.values.hashParams)

            // Use `replace` so legacy settings URLs don't become dead back-button entries.
            if (canonicalSection !== section || didCanonicalizeHashParams) {
                router.actions.replace(
                    urls.settings(canonicalSection as SettingSectionId),
                    router.values.searchParams,
                    hashParams
                )
                return
            }

            if (SettingLevelIds.includes(section as SettingLevelId)) {
                // Redirect level-only URLs to the first section at that level
                const level = section as SettingLevelId
                const effectiveLevel = level === 'environment' ? 'project' : level

                // If a section at this level is already selected (e.g. the user clicked the
                // "Settings" nav link while already viewing a settings page here), don't redirect.
                // Otherwise the level-only URL bounces straight back to the section, a no-op URL
                // rewrite that flickers and makes the link feel broken.
                const selectedSectionLevel = values.sections.find((s) => s.id === values.selectedSectionId)?.level
                if (values.selectedSectionId && selectedSectionLevel === effectiveLevel) {
                    return
                }

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
        // Replace history for level changes, so the environments<>project redirect doesn't leave dead history entries.
        // Section/setting changes push real history entries so the back button works between settings.
        selectLevel({ level }) {
            return [urls.settings(level), router.values.searchParams, router.values.hashParams, { replace: true }]
        },
        selectSection({ section }) {
            return [urls.settings(section), router.values.searchParams, router.values.hashParams]
        },
        selectSetting({ setting }) {
            return [
                urls.settings(values.selectedSectionId ?? values.selectedLevel),
                router.values.searchParams,
                { ...router.values.hashParams, setting },
            ]
        },
    })),
])
