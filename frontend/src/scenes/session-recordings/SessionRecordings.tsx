import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { authorizedUrlListLogic, AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { VersionCheckerBanner } from 'lib/components/VersionChecker/VersionCheckerBanner'
import { useAsyncHandler } from 'lib/hooks/useAsyncHandler'
import { IconSettings } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'
import { sceneLogic } from 'scenes/sceneLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { AndroidRecordingsPromptBanner } from 'scenes/session-recordings/mobile-replay/AndroidRecordingPromptBanner'
import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'
import { AvailableFeature, NotebookNodeType, ReplayTabs } from '~/types'

import { SessionRecordingFilePlayback } from './file-playback/SessionRecordingFilePlayback'
import { createPlaylist } from './playlist/playlistUtils'
import { SessionRecordingsPlaylist } from './playlist/SessionRecordingsPlaylist'
import { SavedSessionRecordingPlaylists } from './saved-playlists/SavedSessionRecordingPlaylists'
import { savedSessionRecordingPlaylistsLogic } from './saved-playlists/savedSessionRecordingPlaylistsLogic'
import { humanFriendlyTabName, sessionRecordingsLogic } from './sessionRecordingsLogic'

export function SessionsRecordings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { tab } = useValues(sessionRecordingsLogic)
    const recordingsDisabled = currentTeam && !currentTeam?.session_recording_opt_in
    const { reportRecordingPlaylistCreated } = useActions(eventUsageLogic)
    const { guardAvailableFeature } = useActions(sceneLogic)
    const playlistsLogic = savedSessionRecordingPlaylistsLogic({ tab: ReplayTabs.Recent })
    const { playlists } = useValues(playlistsLogic)
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)

    const theAuthorizedUrlsLogic = authorizedUrlListLogic({
        actionId: null,
        type: AuthorizedUrlListType.RECORDING_DOMAINS,
    })
    const { suggestions, authorizedUrls } = useValues(theAuthorizedUrlsLogic)
    const mightBeRefusingRecordings = suggestions.length > 0 && authorizedUrls.length > 0

    const newPlaylistHandler = useAsyncHandler(async () => {
        await createPlaylist({}, true)
        reportRecordingPlaylistCreated('new')
    })

    // NB this relies on `updateSearchParams` being the only prop needed to pick the correct "Recent" tab list logic
    const { filters, totalFiltersCount } = useValues(sessionRecordingsPlaylistLogic({ updateSearchParams: true }))
    const saveFiltersPlaylistHandler = useAsyncHandler(async () => {
        await createPlaylist({ filters }, true)
        reportRecordingPlaylistCreated('filters')
    })

    return (
        <div>
            <PageHeader
                buttons={
                    <>
                        {tab === ReplayTabs.Recent && !recordingsDisabled && (
                            <>
                                <NotebookSelectButton
                                    resource={{
                                        type: NotebookNodeType.RecordingPlaylist,
                                        attrs: { filters: filters },
                                    }}
                                    type="secondary"
                                />
                                <LemonButton
                                    fullWidth={false}
                                    data-attr="session-recordings-filters-save-as-playlist"
                                    type="primary"
                                    onClick={(e) =>
                                        guardAvailableFeature(
                                            AvailableFeature.RECORDINGS_PLAYLISTS,
                                            'recording playlists',
                                            "Playlists allow you to save certain session recordings as a group to easily find and watch them again in the future. You've unfortunately run out of playlists on your current subscription plan.",
                                            () => {
                                                // choose the type of playlist handler so that analytics correctly report
                                                // whether filters have been changed before saving
                                                totalFiltersCount === 0
                                                    ? newPlaylistHandler.onEvent?.(e)
                                                    : saveFiltersPlaylistHandler.onEvent?.(e)
                                            },
                                            undefined,
                                            playlists.count
                                        )
                                    }
                                >
                                    Save as playlist
                                </LemonButton>
                                <LemonButton
                                    type="secondary"
                                    icon={<IconSettings />}
                                    onClick={() => openSettingsPanel({ sectionId: 'project-replay' })}
                                >
                                    Configure
                                </LemonButton>
                            </>
                        )}

                        {tab === ReplayTabs.Playlists && (
                            <LemonButton
                                type="primary"
                                onClick={(e) =>
                                    guardAvailableFeature(
                                        AvailableFeature.RECORDINGS_PLAYLISTS,
                                        'recording playlists',
                                        "Playlists allow you to save certain session recordings as a group to easily find and watch them again in the future. You've unfortunately run out of playlists on your current subscription plan.",
                                        () => newPlaylistHandler.onEvent?.(e),
                                        undefined,
                                        playlists.count
                                    )
                                }
                                data-attr="save-recordings-playlist-button"
                                loading={newPlaylistHandler.loading}
                            >
                                New playlist
                            </LemonButton>
                        )}
                    </>
                }
            />
            <LemonTabs
                activeKey={tab}
                onChange={(t) => router.actions.push(urls.replay(t as ReplayTabs))}
                tabs={Object.values(ReplayTabs).map((replayTab) => ({
                    label: humanFriendlyTabName(replayTab),
                    key: replayTab,
                }))}
            />
            <div className="space-y-2">
                <VersionCheckerBanner />
                <AndroidRecordingsPromptBanner context="replay" />

                {recordingsDisabled ? (
                    <LemonBanner
                        type="info"
                        action={{
                            type: 'secondary',
                            icon: <IconSettings />,
                            onClick: () => openSettingsPanel({ sectionId: 'project-replay' }),
                            children: 'Configure',
                        }}
                    >
                        Session recordings are currently disabled for this project.
                    </LemonBanner>
                ) : null}

                {!recordingsDisabled && mightBeRefusingRecordings ? (
                    <LemonBanner
                        type="warning"
                        action={{
                            type: 'secondary',
                            icon: <IconSettings />,
                            onClick: () => openSettingsPanel({ sectionId: 'project-replay' }),
                            children: 'Configure',
                        }}
                        dismissKey={`session-recordings-authorized-domains-warning/${suggestions.join(',')}`}
                    >
                        You have unauthorized domains trying to send recordings. To accept recordings from these
                        domains, please check your config.
                    </LemonBanner>
                ) : null}

                {!tab ? (
                    <Spinner />
                ) : tab === ReplayTabs.Recent ? (
                    <div className="SessionRecordingPlaylistHeightWrapper">
                        <SessionRecordingsPlaylist updateSearchParams />
                    </div>
                ) : tab === ReplayTabs.Playlists ? (
                    <SavedSessionRecordingPlaylists tab={ReplayTabs.Playlists} />
                ) : tab === ReplayTabs.FilePlayback ? (
                    <SessionRecordingFilePlayback />
                ) : null}
            </div>
        </div>
    )
}

export const scene: SceneExport = {
    component: SessionsRecordings,
    logic: sessionRecordingsLogic,
}
