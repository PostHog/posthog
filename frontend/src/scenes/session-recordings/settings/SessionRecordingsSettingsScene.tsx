import { kea, path, selectors } from 'kea'
import { router } from 'kea-router'

import { Scene, SceneExport } from 'scenes/sceneTypes'
import { Settings } from 'scenes/settings/Settings'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { Breadcrumb } from '~/types'

import { SessionRecordingsPageTabs } from '../SessionRecordings'
import type { sessionRecordingsSettingsSceneLogicType } from './SessionRecordingsSettingsSceneType'

const SETTINGS_LOGIC_KEY = 'replaySettings'

export const sessionRecordingsSettingsSceneLogic = kea<sessionRecordingsSettingsSceneLogicType>([
    path(['scenes', 'session-recordings', 'settings', 'sessionRecordingsSettingsSceneLogic']),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.Replay,
                    path: urls.replay(),
                    name: 'Replay',
                    iconType: 'session_replay',
                },
                {
                    key: Scene.ReplaySettings,
                    path: urls.replaySettings(),
                    name: 'Settings',
                    iconType: 'session_replay',
                },
            ],
        ],
    }),
])

export const scene: SceneExport = {
    component: SessionRecordingsSettingsScene,
    logic: sessionRecordingsSettingsSceneLogic,
    settingSectionId: 'environment-replay',
}

export function SessionRecordingsSettingsScene(): JSX.Element {
    return (
        <>
            <SceneContent className="-mb-14">
                <SessionRecordingsPageTabs />
                <Settings
                    logicKey={SETTINGS_LOGIC_KEY}
                    sectionId="environment-replay"
                    settingId={router.values.searchParams.sectionId || 'replay'}
                    handleLocally
                />
            </SceneContent>
        </>
    )
}
