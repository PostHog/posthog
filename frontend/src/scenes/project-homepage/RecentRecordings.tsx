import { dayjs } from 'lib/dayjs'
import { useActions, useValues } from 'kea'

import './ProjectHomepage.scss'
import { CompactList } from 'lib/components/CompactList/CompactList'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { urls } from 'scenes/urls'
import { SessionRecordingType } from '~/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { humanFriendlyDuration } from 'lib/utils'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { SessionPlayerModal } from 'scenes/session-recordings/player/modal/SessionPlayerModal'
import { teamLogic } from 'scenes/teamLogic'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { ProjectHomePageCompactListItem } from './ProjectHomePageCompactListItem'
import { asDisplay } from 'scenes/persons/person-utils'

interface RecordingRowProps {
    recording: SessionRecordingType
}

export function RecordingRow({ recording }: RecordingRowProps): JSX.Element {
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)
    const { reportRecordingOpenedFromRecentRecordingList } = useActions(eventUsageLogic)

    return (
        <ProjectHomePageCompactListItem
            title={asDisplay(recording.person)}
            subtitle={`Recorded ${dayjs(recording.start_time).fromNow()}`}
            prefix={<ProfilePicture name={asDisplay(recording.person)} />}
            suffix={
                <div className="flex items-center justify-end text-default">
                    <span>{humanFriendlyDuration(recording.recording_duration)}</span>
                    <IconPlayCircle className="text-2xl ml-2" />
                </div>
            }
            onClick={() => {
                openSessionPlayer({
                    id: recording.id,
                    matching_events: recording.matching_events,
                })
                reportRecordingOpenedFromRecentRecordingList()
            }}
        />
    )
}

export function RecentRecordings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const sessionRecordingsListLogicInstance = sessionRecordingsPlaylistLogic({ logicKey: 'projectHomepage' })
    const { sessionRecordings, sessionRecordingsResponseLoading } = useValues(sessionRecordingsListLogicInstance)

    return (
        <>
            <SessionPlayerModal />
            <CompactList
                title="Recent recordings"
                viewAllURL={urls.replay()}
                loading={sessionRecordingsResponseLoading}
                emptyMessage={
                    currentTeam?.session_recording_opt_in
                        ? {
                              title: 'There are no recordings for this project',
                              description: 'Make sure you have the javascript snippet setup in your website.',
                              buttonText: 'Learn more',
                              buttonTo: 'https://posthog.com/docs/user-guides/recordings',
                          }
                        : {
                              title: 'Recordings are not enabled for this project',
                              description: 'Once recordings are enabled, new recordings will display here.',
                              buttonText: 'Enable recordings',
                              buttonTo: urls.projectSettings() + '#recordings',
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
