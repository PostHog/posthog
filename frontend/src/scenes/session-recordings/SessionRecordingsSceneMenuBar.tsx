import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconDocument, IconGear, IconHeadset, IconVideoCamera } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { LiveRecordingsCount } from 'scenes/session-recordings/components/LiveRecordingsCount'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { ReplayLayout, STAFF_REPLAY_LAYOUTS } from 'scenes/session-recordings/playlist/replayLayout'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { ReplayTabs } from '~/types'

import { sessionReplaySceneLogic } from './sessionReplaySceneLogic'

const RESOURCE_TYPE = 'replay'

const STAFF_REPLAY_LAYOUT_LABELS: Partial<Record<ReplayLayout, string>> = {
    classic: 'Legacy',
    compact: 'Compact',
    youtube: 'YouTube',
}

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
    const { watchLayoutOffered, replayLayout, canOverrideLayout } = useValues(playerSettingsLogic)
    const { setPreferClassicReplayLayout, setStaffLayoutOverride } = useActions(playerSettingsLogic)
    const recordingsDisabled = currentTeam && !currentTeam.session_recording_opt_in

    // Every item belongs to the recordings tab, so the collections tab gets no bar.
    if (tab !== ReplayTabs.Home || recordingsDisabled) {
        return null
    }

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'playback',
            id: `${RESOURCE_TYPE}-menubar-file-playback`,
            label: 'Playback from PostHog JSON file',
            icon: <IconDocument />,
            onSelect: () => router.actions.push(urls.replayFilePlayback()),
        },
        {
            group: 'file',
            section: 'settings',
            id: `${RESOURCE_TYPE}-menubar-settings`,
            label: 'Settings',
            icon: <IconGear />,
            onSelect: () => router.actions.push(urls.replaySettings()),
            pinned: { order: 3, variant: 'secondary', dataAttr: 'session-recordings-settings-button' },
        },
        {
            group: 'view',
            section: 'navigate',
            id: `${RESOURCE_TYPE}-menubar-kiosk`,
            label: 'Kiosk mode',
            icon: <IconHeadset />,
            onSelect: () => router.actions.push(urls.replayKiosk()),
        },
        {
            group: 'view',
            section: 'navigate',
            type: 'panel',
            id: `${RESOURCE_TYPE}-menubar-live-recordings`,
            label: 'Live recordings',
            icon: <IconVideoCamera />,
            render: () => <LiveRecordingsCount />,
            pinned: { order: 2, variant: 'icon', render: () => <LiveRecordingsCount /> },
        },
        ...(!canOverrideLayout && watchLayoutOffered
            ? ([
                  {
                      group: 'view',
                      section: 'layout',
                      type: 'radio',
                      // pinned: option data-attrs `replay-layout-switch-${value}` are wire strings
                      id: 'replay-layout-switch',
                      label: 'Layout',
                      value: replayLayout === 'classic' ? 'classic' : 'new',
                      options: [
                          { value: 'new', label: 'New layout' },
                          { value: 'classic', label: 'Legacy' },
                      ],
                      onValueChange: (value) => setPreferClassicReplayLayout(value === 'classic'),
                      pinned: { order: 1, variant: 'secondary' },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(canOverrideLayout
            ? ([
                  {
                      group: 'staff',
                      type: 'radio',
                      // pinned: option data-attrs `replay-layout-override-${value}` are wire strings
                      id: 'replay-layout-override',
                      label: 'Layout',
                      value: replayLayout,
                      options: STAFF_REPLAY_LAYOUTS.map((layout) => ({
                          value: layout,
                          label: STAFF_REPLAY_LAYOUT_LABELS[layout] ?? layout,
                      })),
                      onValueChange: (value) => setStaffLayoutOverride(value as ReplayLayout),
                      pinned: { order: 1, variant: 'secondary' },
                  },
              ] satisfies SceneAction[])
            : []),
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
