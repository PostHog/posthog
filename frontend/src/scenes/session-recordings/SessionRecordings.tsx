import { IconEllipsis, IconGear } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { authorizedUrlListLogic, AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { VersionCheckerBanner } from 'lib/components/VersionChecker/VersionCheckerBanner'
import { useAsyncHandler } from 'lib/hooks/useAsyncHandler'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'
import { SceneExport } from 'scenes/sceneTypes'
import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'
import { AvailableFeature, NotebookNodeType, ReplayTabs } from '~/types'

import { SessionRecordingErrors } from './errors/SessionRecordingErrors'
import { createPlaylist } from './playlist/playlistUtils'
import { SessionRecordingsPlaylist } from './playlist/SessionRecordingsPlaylist'
import { SavedSessionRecordingPlaylists } from './saved-playlists/SavedSessionRecordingPlaylists'
import { savedSessionRecordingPlaylistsLogic } from './saved-playlists/savedSessionRecordingPlaylistsLogic'
import { humanFriendlyTabName, sessionReplaySceneLogic } from './sessionReplaySceneLogic'

function Header(): JSX.Element {
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const playlistsLogic = savedSessionRecordingPlaylistsLogic({ tab: ReplayTabs.Recent })
    const { playlists } = useValues(playlistsLogic)
    const { tab } = useValues(sessionReplaySceneLogic)
    const { currentTeam } = useValues(teamLogic)
    const recordingsDisabled = currentTeam && !currentTeam?.session_recording_opt_in
    const { reportRecordingPlaylistCreated } = useActions(eventUsageLogic)

    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)

    // NB this relies on `updateSearchParams` being the only prop needed to pick the correct "Recent" tab list logic
    const { filters, totalFiltersCount } = useValues(sessionRecordingsPlaylistLogic({ updateSearchParams: true }))
    const saveFiltersPlaylistHandler = useAsyncHandler(async () => {
        await createPlaylist({ filters }, true)
        reportRecordingPlaylistCreated('filters')
    })

    const newPlaylistHandler = useAsyncHandler(async () => {
        await createPlaylist({}, true)
        reportRecordingPlaylistCreated('new')
    })

    return (
        <PageHeader
            buttons={
                <>
                    {tab === ReplayTabs.Recent && !recordingsDisabled && (
                        <>
                            <LemonMenu
                                items={[
                                    {
                                        label: 'Playback from file',
                                        to: urls.replayFilePlayback(),
                                    },
                                ]}
                            >
                                <LemonButton icon={<IconEllipsis />} />
                            </LemonMenu>
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
                                        () => {
                                            // choose the type of playlist handler so that analytics correctly report
                                            // whether filters have been changed before saving
                                            totalFiltersCount === 0
                                                ? newPlaylistHandler.onEvent?.(e)
                                                : saveFiltersPlaylistHandler.onEvent?.(e)
                                        },
                                        { currentUsage: playlists.count }
                                    )
                                }
                            >
                                Save as playlist
                            </LemonButton>
                            <LemonButton
                                type="secondary"
                                icon={<IconGear />}
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
                                    () => newPlaylistHandler.onEvent?.(e),
                                    { currentUsage: playlists.count }
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
    )
}

function Warnings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const recordingsDisabled = currentTeam && !currentTeam?.session_recording_opt_in

    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)

    const theAuthorizedUrlsLogic = authorizedUrlListLogic({
        actionId: null,
        type: AuthorizedUrlListType.RECORDING_DOMAINS,
    })
    const { suggestions, authorizedUrls } = useValues(theAuthorizedUrlsLogic)
    const mightBeRefusingRecordings = suggestions.length > 0 && authorizedUrls.length > 0

    return (
        <>
            <VersionCheckerBanner />

            {recordingsDisabled ? (
                <LemonBanner
                    type="info"
                    action={{
                        type: 'primary',
                        icon: <IconGear />,
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
                        icon: <IconGear />,
                        onClick: () => openSettingsPanel({ sectionId: 'project-replay' }),
                        children: 'Configure',
                    }}
                    dismissKey={`session-recordings-authorized-domains-warning/${suggestions.join(',')}`}
                >
                    You have unauthorized domains trying to send recordings. To accept recordings from these domains,
                    please check your config.
                </LemonBanner>
            ) : null}
        </>
    )
}

function MainPanel(): JSX.Element {
    const { tab } = useValues(sessionReplaySceneLogic)

    return (
        <div className="space-y-2">
            <Warnings />

            {!tab ? (
                <Spinner />
            ) : tab === ReplayTabs.Recent ? (
                <div className="SessionRecordingPlaylistHeightWrapper">
                    <SessionRecordingsPlaylist updateSearchParams />
                </div>
            ) : tab === ReplayTabs.Playlists ? (
                <SavedSessionRecordingPlaylists tab={ReplayTabs.Playlists} />
            ) : tab === ReplayTabs.Errors ? (
                <SessionRecordingErrors />
            ) : null}
        </div>
    )
}

function PageTabs(): JSX.Element {
    const { tab, tabs } = useValues(sessionReplaySceneLogic)

    return (
        <LemonTabs
            activeKey={tab}
            onChange={(t) => router.actions.push(urls.replay(t as ReplayTabs))}
            tabs={tabs.map((replayTab) => {
                return {
                    label: humanFriendlyTabName(replayTab),
                    key: replayTab,
                }
            })}
        />
    )
}
export function SessionsRecordings(): JSX.Element {
    return (
        <>
            <Header />
            <PageTabs />
            <MainPanel />
        </>
    )
}

export const scene: SceneExport = {
    component: SessionsRecordings,
    logic: sessionReplaySceneLogic,
}
