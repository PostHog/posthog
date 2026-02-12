import { BindLogic, kea, path, selectors } from 'kea'
import { router } from 'kea-router'

import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { Settings } from 'scenes/settings/Settings'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { Breadcrumb } from '~/types'

import { SessionRecordingsPageTabs } from '../SessionRecordings'
import { sessionReplaySceneLogic } from '../sessionReplaySceneLogic'
import type { sessionRecordingsSettingsSceneLogicType } from './SessionRecordingsSettingsSceneType'

export const SETTINGS_LOGIC_KEY = 'replaySettings'

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
    productKey: ProductKey.SESSION_REPLAY,
}

export interface SessionRecordingsSettingsSceneProps {
    tabId?: string
}

export function SessionRecordingsSettingsScene({ tabId }: SessionRecordingsSettingsSceneProps = {}): JSX.Element {
    if (!tabId) {
        throw new Error('<SessionRecordingsSettingsScene /> must receive a tabId prop')
    }
    return (
        <BindLogic logic={sessionReplaySceneLogic} props={{ tabId }}>
            <SceneContent className="-mb-14">
                <SceneTitleSection
                    name={sceneConfigurations[Scene.Replay].name}
                    resourceType={{
                        type: sceneConfigurations[Scene.Replay].iconType || 'default_icon_type',
                    }}
                />
                <SessionRecordingsPageTabs />
                <Settings
                    logicKey={SETTINGS_LOGIC_KEY}
                    sectionId="environment-replay"
                    settingId={router.values.searchParams.sectionId || 'replay'}
                    handleLocally
                />
            </SceneContent>
        </BindLogic>
    )
}
