import { LemonBanner, LemonButton, Link, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Playlist, PlaylistSection } from 'lib/components/Playlist/Playlist'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'
import { urls } from 'scenes/urls'

import { ReplayTabs, SessionRecordingType } from '~/types'

import { SessionRecordingPreview } from '../playlist/SessionRecordingPreview'
import { DEFAULT_RECORDING_FILTERS, sessionRecordingsPlaylistLogic } from '../playlist/sessionRecordingsPlaylistLogic'
import {
    SessionRecordingPlaylistBottomSettings,
    SessionRecordingsPlaylistTopSettings,
} from '../playlist/SessionRecordingsPlaylistSettings'
import { SessionRecordingsPlaylistTroubleshooting } from '../playlist/SessionRecordingsPlaylistTroubleshooting'

export const PanelPlaylist = ({ isCollapsed }: { isCollapsed: boolean }): JSX.Element => {
    const {
        filters,
        pinnedRecordings,
        sessionRecordingsResponseLoading,
        otherRecordings,
        activeSessionRecordingId,
        hasNext,
    } = useValues(sessionRecordingsPlaylistLogic)
    const { maybeLoadSessionRecordings, setSelectedRecordingId, setFilters, setShowOtherRecordings } =
        useActions(sessionRecordingsPlaylistLogic)

    const notebookNode = useNotebookNode()

    const { featureFlags } = useValues(featureFlagLogic)
    const isTestingSaved = featureFlags[FEATURE_FLAGS.SAVED_NOT_PINNED] === 'test'

    const pinnedDescription = isTestingSaved ? 'Saved' : 'Pinned'

    const sections: PlaylistSection<SessionRecordingType>[] = []

    if (pinnedRecordings.length) {
        sections.push({
            key: 'pinned',
            title: `${pinnedDescription} recordings`,
            items: pinnedRecordings,
            render: ({ item, isActive }) => (
                <SessionRecordingPreview recording={item} isActive={isActive} pinned={true} />
            ),
            initiallyOpen: true,
        })
    }

    sections.push({
        key: 'other',
        title: 'Other recordings',
        items: otherRecordings,
        render: ({ item, isActive }) => <SessionRecordingPreview recording={item} isActive={isActive} pinned={false} />,
        footer: (
            <div className="p-4">
                <div className="h-10 flex items-center justify-center gap-2 text-muted-alt">
                    {sessionRecordingsResponseLoading ? (
                        <>
                            <Spinner textColored /> Loading older recordings
                        </>
                    ) : hasNext ? (
                        <LemonButton onClick={() => maybeLoadSessionRecordings('older')}>Load more</LemonButton>
                    ) : (
                        'No more results'
                    )}
                </div>
            </div>
        ),
    })

    return (
        <Playlist
            isCollapsed={isCollapsed}
            data-attr="session-recordings-playlist"
            notebooksHref={urls.replay(ReplayTabs.Home, filters)}
            title="Results"
            embedded={!!notebookNode}
            sections={sections}
            onChangeSections={(activeSections) => setShowOtherRecordings(activeSections.includes('other'))}
            headerActions={<SessionRecordingsPlaylistTopSettings filters={filters} setFilters={setFilters} />}
            footerActions={<SessionRecordingPlaylistBottomSettings />}
            loading={sessionRecordingsResponseLoading}
            onScrollListEdge={(edge) => {
                if (edge === 'top') {
                    maybeLoadSessionRecordings('newer')
                } else {
                    maybeLoadSessionRecordings('older')
                }
            }}
            listEmptyState={<ListEmptyState />}
            onSelect={(item) => setSelectedRecordingId(item.id)}
            activeItemId={activeSessionRecordingId}
            content={null}
        />
    )
}

const ListEmptyState = (): JSX.Element => {
    const { filters, sessionRecordingsAPIErrored, unusableEventsInFilter } = useValues(sessionRecordingsPlaylistLogic)
    const { setFilters } = useActions(sessionRecordingsPlaylistLogic)

    return (
        <div className="p-3 text-sm text-muted-alt">
            {sessionRecordingsAPIErrored ? (
                <LemonBanner type="error">Error while trying to load recordings.</LemonBanner>
            ) : unusableEventsInFilter.length ? (
                <UnusableEventsWarning unusableEventsInFilter={unusableEventsInFilter} />
            ) : (
                <div className="flex flex-col items-center space-y-2">
                    {filters.date_from === DEFAULT_RECORDING_FILTERS.date_from ? (
                        <>
                            <span>No matching recordings found</span>
                            <LemonButton
                                type="secondary"
                                data-attr="expand-replay-listing-from-default-seven-days-to-twenty-one"
                                onClick={() => setFilters({ date_from: '-30d' })}
                            >
                                Search over the last 30 days
                            </LemonButton>
                        </>
                    ) : (
                        <SessionRecordingsPlaylistTroubleshooting />
                    )}
                </div>
            )}
        </div>
    )
}

function UnusableEventsWarning(props: { unusableEventsInFilter: string[] }): JSX.Element {
    // TODO add docs on how to enrich custom events with session_id and link to it from here
    return (
        <LemonBanner type="warning">
            <p>Cannot use these events to filter for session recordings:</p>
            <li className="my-1">
                {props.unusableEventsInFilter.map((event) => (
                    <span key={event}>"{event}"</span>
                ))}
            </li>
            <p>
                Events have to have a <PropertyKeyInfo value="$session_id" /> to be used to filter recordings. This is
                added automatically by{' '}
                <Link to="https://posthog.com/docs/libraries/js" target="_blank">
                    the Web SDK
                </Link>
                ,{' '}
                <Link to="https://posthog.com/docs/libraries" target="_blank">
                    and the Mobile SDKs (Android, iOS, React Native and Flutter)
                </Link>
            </p>
        </LemonBanner>
    )
}
