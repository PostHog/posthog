import { dayjs } from 'lib/dayjs'
import { useValues } from 'kea'

import './ProjectHomepage.scss'
import { CompactList } from 'lib/components/CompactList/CompactList'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { asDisplay } from 'scenes/persons/PersonHeader'
import { sessionRecordingsListLogic } from 'scenes/session-recordings/playlist/sessionRecordingsListLogic'
import { urls } from 'scenes/urls'
import { SessionRecordingType } from '~/types'
import { humanFriendlyDuration } from 'lib/utils'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { teamLogic } from 'scenes/teamLogic'
import { ProjectHomePageCompactListItem } from './ProjectHomePageCompactListItem'

interface RecordingRowProps {
    recording: SessionRecordingType
    url?: string
}

export function RecordingRow({ recording, url }: RecordingRowProps): JSX.Element {
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
            to={url || urls.sessionRecordings(undefined, { sessionRecordingId: recording.id })}
        />
    )
}

export function RecentRecordings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const sessionRecordingsListLogicInstance = sessionRecordingsListLogic({ key: 'projectHomepage' })
    const { sessionRecordings, sessionRecordingsResponseLoading } = useValues(sessionRecordingsListLogicInstance)

    return (
        <>
            <CompactList
                title="Recent recordings"
                viewAllURL={urls.sessionRecordings()}
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
