import { kea, path, selectors } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { Settings } from 'scenes/settings/Settings'
import { urls } from 'scenes/urls'

import { ReplayTabs } from '~/types'
import { Breadcrumb } from '~/types'

import { humanFriendlyTabName } from '../sessionReplaySceneLogic'
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
                },
                {
                    key: Scene.ReplaySettings,
                    path: urls.replaySettings(),
                    name: 'Settings',
                },
            ],
        ],
    }),
])

export const scene: SceneExport = {
    component: SessionRecordingsSettingsScene,
    logic: sessionRecordingsSettingsSceneLogic,
}

export function SessionRecordingsSettingsScene(): JSX.Element {
    return (
        <>
            <div className="-mb-14">
                <PageHeader />
                <LemonTabs
                    activeKey={ReplayTabs.Settings}
                    onChange={(t) => router.actions.push(urls.replay(t as ReplayTabs))}
                    tabs={Object.values(ReplayTabs).map((replayTab) => {
                        return {
                            label: <>{humanFriendlyTabName(replayTab)}</>,
                            key: replayTab,
                        }
                    })}
                />
                <Settings
                    logicKey={SETTINGS_LOGIC_KEY}
                    sectionId="environment-replay"
                    settingId={router.values.searchParams.sectionId || 'replay'}
                    handleLocally
                />
            </div>
        </>
    )
}
