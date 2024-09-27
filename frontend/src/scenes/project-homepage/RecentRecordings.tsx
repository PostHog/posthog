import './ProjectHomepage.scss'

import { useActions, useValues } from 'kea'
import { CompactList } from 'lib/components/CompactList/CompactList'
import { dayjs } from 'lib/dayjs'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { humanFriendlyDuration } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { asDisplay } from 'scenes/persons/person-utils'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SessionRecordingType } from '~/types'

import { ProjectHomePageCompactListItem } from './ProjectHomePageCompactListItem'

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
                <div className="flex items-center justify-end text-text-3000">
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
                              buttonTo: urls.settings('project-replay'),
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
