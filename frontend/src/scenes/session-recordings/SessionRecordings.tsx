import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconDocument, IconGear, IconHeadset } from '@posthog/icons'
import { LemonBadge, LemonButton, Link } from '@posthog/lemon-ui'
import { PostHogCaptureOnViewed } from '@posthog/react'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LiveRecordingsCount } from 'lib/components/LiveUserCount'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { cn } from 'lib/utils/css-classes'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ScenePanel, ScenePanelActionsSection } from '~/layout/scenes/SceneLayout'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, ReplayTab, ReplayTabs } from '~/types'

import { sessionReplayEmptyState } from 'products/replay/frontend/emptyState/sessionReplayEmptyState'

import { SessionRecordingCollections } from './collections/SessionRecordingCollections'
import { SessionRecordingsPlaylistRedesign } from './playlist-redesign/SessionRecordingsPlaylistRedesign'
import { createPlaylist } from './playlist/playlistUtils'
import { SessionRecordingsPlaylist } from './playlist/SessionRecordingsPlaylist'
import {
    SessionRecordingPlaylistLogicProps,
    sessionRecordingsPlaylistLogic,
} from './playlist/sessionRecordingsPlaylistLogic'
import { sessionRecordingEventUsageLogic } from './sessionRecordingEventUsageLogic'
import { sessionReplaySceneLogic } from './sessionReplaySceneLogic'
import SessionRecordingTemplates from './templates/SessionRecordingTemplates'

function Header(): JSX.Element {
    const { tab } = useValues(sessionReplaySceneLogic)
    const { currentTeam } = useValues(teamLogic)
    const recordingsDisabled = currentTeam && !currentTeam?.session_recording_opt_in
    const { reportRecordingPlaylistCreated } = useActions(sessionRecordingEventUsageLogic)
    const [loading, setLoading] = useState(false)
    const handleNewPlaylist = async (): Promise<void> => {
        setLoading(true)
        try {
            await createPlaylist({ _create_in_folder: 'Unfiled/Replay playlists', type: 'collection' }, true)
            reportRecordingPlaylistCreated('new')
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="flex items-center gap-2">
            {tab === ReplayTabs.Home && !recordingsDisabled && (
                <>
                    <LiveRecordingsCount />
                    <ScenePanel>
                        <ScenePanelActionsSection>
                            <Link
                                to={urls.replayFilePlayback()}
                                buttonProps={{
                                    menuItem: true,
                                }}
                            >
                                <IconDocument /> Playback from PostHog JSON file
                            </Link>
                            <Link
                                to={urls.replayKiosk()}
                                buttonProps={{
                                    menuItem: true,
                                }}
                            >
                                <IconHeadset /> Kiosk mode
                            </Link>
                        </ScenePanelActionsSection>
                    </ScenePanel>
                </>
            )}

            {tab === ReplayTabs.Playlists && (
                <AccessControlAction
                    resourceType={AccessControlResourceType.SessionRecording}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <Shortcut
                        name="NewRecordingCollection"
                        keybind={[keyBinds.new]}
                        intent="New collection"
                        interaction="click"
                        scope={Scene.Replay}
                    >
                        <LemonButton
                            type="primary"
                            onClick={handleNewPlaylist}
                            data-attr="save-recordings-playlist-button"
                            loading={loading}
                            size="small"
                            tooltip="New collection"
                        >
                            New collection
                        </LemonButton>
                    </Shortcut>
                </AccessControlAction>
            )}

            <LemonButton
                icon={<IconGear />}
                type="secondary"
                size="small"
                to={urls.replaySettings()}
                data-attr="session-recordings-settings-button"
            >
                Settings
            </LemonButton>
        </div>
    )
}

const REPLAY_VISION_PROMO_DISMISS_KEY = 'replay-vision-launch-promo'

function ReplayVisionPromoBanner(): JSX.Element | null {
    const { isDismissed } = useValues(lemonBannerLogic({ dismissKey: REPLAY_VISION_PROMO_DISMISS_KEY }))

    // A dismissed LemonBanner renders null but the viewed tracker would still fire, skewing impressions
    if (isDismissed) {
        return null
    }

    return (
        <PostHogCaptureOnViewed name="replay-vision-launch-banner-shown">
            <LemonBanner
                type="ai"
                dismissKey={REPLAY_VISION_PROMO_DISMISS_KEY}
                action={{
                    children: 'Try Replay vision',
                    to: urls.replayVision(),
                    center: true,
                    'data-attr': 'replay-vision-launch-banner-cta',
                }}
            >
                Replay vision is here. Scanners watch your recordings for you and surface what matters.
            </LemonBanner>
        </PostHogCaptureOnViewed>
    )
}

// Keeps the recordings logic mounted for the scene's lifetime so its state survives tab
// switches. Rendered only on the Home tab so landing on Collections/Templates does not mount
// it — which would otherwise fire a wasted loadSessionRecordings ClickHouse query on load.
function AttachScenePlaylistLogic({
    playlistLogicProps,
}: {
    playlistLogicProps: SessionRecordingPlaylistLogicProps
}): null {
    useAttachedLogic(sessionRecordingsPlaylistLogic(playlistLogicProps), sessionReplaySceneLogic())
    return null
}

function MainPanel(): JSX.Element {
    const { tab } = useValues(sessionReplaySceneLogic)
    const isRedesignEnabled = useFeatureFlag('REPLAY_UI_REDESIGN_2026', 'test')

    const playlistLogicProps: SessionRecordingPlaylistLogicProps = {
        logicKey: 'scene',
        updateSearchParams: true,
    }

    return (
        <div className={cn('flex flex-col gap-y-4', ReplayTabs.Home === tab && 'grow')}>
            <ReplayVisionPromoBanner />

            {!tab ? (
                <Spinner />
            ) : tab === ReplayTabs.Home ? (
                <div className="SessionRecordingPlaylistHeightWrapper grow">
                    <AttachScenePlaylistLogic playlistLogicProps={playlistLogicProps} />
                    {isRedesignEnabled ? (
                        <SessionRecordingsPlaylistRedesign {...playlistLogicProps} />
                    ) : (
                        <SessionRecordingsPlaylist {...playlistLogicProps} />
                    )}
                </div>
            ) : tab === ReplayTabs.Playlists ? (
                <SessionRecordingCollections />
            ) : tab === ReplayTabs.Templates ? (
                <SessionRecordingTemplates />
            ) : null}
        </div>
    )
}

const ReplayPageTabs: ReplayTab[] = [
    {
        label: 'Recordings',
        tooltipDocLink: 'https://posthog.com/docs/session-replay/tutorials',
        key: ReplayTabs.Home,
        'data-attr': 'session-recordings-home-tab',
    },
    {
        label: 'Collections',
        tooltipDocLink: 'https://posthog.com/docs/session-replay/how-to-watch-recordings',
        key: ReplayTabs.Playlists,
        tooltip: 'View & create collections',
        'data-attr': 'session-recordings-collections-tab',
    },
    {
        label: 'Filter templates',
        key: ReplayTabs.Templates,
        'data-attr': 'session-recordings-templates-tab',
    },
]

export function SessionRecordingsPageTabs(): JSX.Element {
    const { tab, shouldShowNewBadge } = useValues(sessionReplaySceneLogic)
    return (
        <LemonTabs
            activeKey={tab}
            onChange={(t) => router.actions.push(urls.replay(t as ReplayTabs))}
            sceneInset
            className="-mt-4"
            tabs={ReplayPageTabs.map((replayTab): LemonTab<string> => {
                return {
                    label: (
                        <>
                            {replayTab.label}
                            {replayTab.label === ReplayTabs.Templates && shouldShowNewBadge && (
                                <LemonBadge className="ml-1" size="small" />
                            )}
                        </>
                    ),
                    key: replayTab.key,
                    link: urls.replay(replayTab.key),
                    tooltip: replayTab.tooltip,
                    tooltipDocLink: replayTab.tooltipDocLink,
                    'data-attr': replayTab['data-attr'],
                }
            })}
        />
    )
}

export function SessionsRecordings(): JSX.Element {
    return (
        <BindLogic logic={sessionReplaySceneLogic} props={{}}>
            <SceneContent className="h-full">
                <SceneTitleSection
                    name={sceneConfigurations[Scene.Replay].name}
                    resourceType={{
                        type: sceneConfigurations[Scene.Replay].iconType || 'default_icon_type',
                    }}
                    actions={<Header />}
                />
                <SessionRecordingsPageTabs />
                <MainPanel />
            </SceneContent>
        </BindLogic>
    )
}

export const scene: SceneExport = {
    component: SessionsRecordings,
    logic: sessionReplaySceneLogic,
    productKey: ProductKey.SESSION_REPLAY,
    emptyState: sessionReplayEmptyState,
}
