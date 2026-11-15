import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconDocument, IconHeadset } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneMenuBar, SceneMenuBarItem, SceneMenuBarMenu } from '~/layout/scenes/components/SceneMenuBar'
import { ReplayTabs } from '~/types'

import { sessionReplaySceneLogic } from './sessionReplaySceneLogic'

const RESOURCE_TYPE = 'replay'

export function SessionRecordingsSceneMenuBar(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    return <SessionRecordingsSceneMenuBarInner />
}

function SessionRecordingsSceneMenuBarInner(): JSX.Element | null {
    const { tab } = useValues(sessionReplaySceneLogic)
    const { currentTeam } = useValues(teamLogic)
    const recordingsDisabled = currentTeam && !currentTeam.session_recording_opt_in

    // Every item belongs to the recordings tab, so the collections tab gets no bar.
    if (tab !== ReplayTabs.Home || recordingsDisabled) {
        return null
    }

    return (
        <SceneMenuBar>
            <SceneMenuBarMenu label="File" dataAttr={`${RESOURCE_TYPE}-menubar-file`}>
                <SceneMenuBarItem
                    onClick={() => router.actions.push(urls.replayFilePlayback())}
                    data-attr={`${RESOURCE_TYPE}-menubar-file-playback`}
                >
                    <IconDocument />
                    Playback from PostHog JSON file
                </SceneMenuBarItem>
            </SceneMenuBarMenu>
            <SceneMenuBarMenu label="View" dataAttr={`${RESOURCE_TYPE}-menubar-view`}>
                <SceneMenuBarItem
                    onClick={() => router.actions.push(urls.replayKiosk())}
                    data-attr={`${RESOURCE_TYPE}-menubar-kiosk`}
                >
                    <IconHeadset />
                    Kiosk mode
                </SceneMenuBarItem>
            </SceneMenuBarMenu>
        </SceneMenuBar>
    )
}
