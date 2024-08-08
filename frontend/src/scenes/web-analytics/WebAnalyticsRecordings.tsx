import { useValues } from 'kea'
import { CompactList } from 'lib/components/CompactList/CompactList'
import { RecordingRow } from 'scenes/project-homepage/RecentRecordings'
import { SessionPlayerModal } from 'scenes/session-recordings/player/modal/SessionPlayerModal'
import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { ReplayTabs, SessionRecordingType } from '~/types'

export function WebAnalyticsRecordingsTile(): JSX.Element {
    const { replayFilters, webAnalyticsFilters } = useValues(webAnalyticsLogic)
    const { currentTeam } = useValues(teamLogic)
    const sessionRecordingsListLogicInstance = sessionRecordingsPlaylistLogic({
        logicKey: 'webAnalytics',
        filters: replayFilters,
    })
    const { sessionRecordings, sessionRecordingsResponseLoading } = useValues(sessionRecordingsListLogicInstance)
    return (
        <>
            <SessionPlayerModal />
            <CompactList
                title="Recent recordings"
                viewAllURL={
                    sessionRecordings.length > 0 ? urls.replay() : urls.replay(ReplayTabs.Recent, replayFilters)
                }
                loading={sessionRecordingsResponseLoading}
                emptyMessage={
                    !currentTeam?.session_recording_opt_in
                        ? {
                              title: 'Recordings are not enabled for this project',
                              description: 'Once recordings are enabled, new recordings will display here.',
                              buttonText: 'Enable recordings',
                              buttonTo: urls.settings('project-replay'),
                          }
                        : webAnalyticsFilters.length > 0
                        ? {
                              title: 'There are no recordings matching the current filters',
                              description: 'Try changing the filters, or view all recordings.',
                              buttonText: 'View all',
                              buttonTo: urls.replay(),
                          }
                        : {
                              title: 'There are no recordings matching this date range',
                              description: 'Make sure you have the javascript snippet setup in your website.',
                              buttonText: 'Learn more',
                              buttonTo: 'https://posthog.com/docs/user-guides/recordings',
                          }
                }
                items={sessionRecordings.slice(0, 5)}
                renderRow={(recording: SessionRecordingType, index) => (
                    <RecordingRow key={index} recording={recording} />
                )}
            />
        </>
    )
}
