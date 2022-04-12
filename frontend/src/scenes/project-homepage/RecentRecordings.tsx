import React from 'react'
import { dayjs } from 'lib/dayjs'
import { useActions, useValues } from 'kea'

import './RecentRecordings.scss'
import { CompactList } from 'lib/components/CompactList/CompactList'
import { LemonButton } from 'lib/components/LemonButton'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { asDisplay } from 'scenes/persons/PersonHeader'
import { sessionRecordingsTableLogic } from 'scenes/session-recordings/sessionRecordingsTableLogic'
import { urls } from 'scenes/urls'
import { SessionRecordingType } from '~/types'
import { RecordingWatchedSource } from 'lib/utils/eventUsageLogic'
import { humanFriendlyDuration } from 'lib/utils'
import { IconPlayCircle } from 'lib/components/icons'
import { SessionPlayerDrawer } from 'scenes/session-recordings/SessionPlayerDrawer'
import { teamLogic } from 'scenes/teamLogic'

interface RecordingRowProps {
    recording: SessionRecordingType
}

function RecordingRow({ recording }: RecordingRowProps): JSX.Element {
    const sessionRecordingsTableLogicInstance = sessionRecordingsTableLogic({ key: 'projectHomepage' })
    const { openSessionPlayer } = useActions(sessionRecordingsTableLogicInstance)
    return (
        <LemonButton
            fullWidth
            className="recording-row"
            onClick={() => {
                openSessionPlayer(recording.id, RecordingWatchedSource.ProjectHomepage)
            }}
        >
            <ProfilePicture name={asDisplay(recording.person)} />
            <div className="recording-person-text-container" style={{ flexDirection: 'column', display: 'flex' }}>
                <p className="recording-person-text">{asDisplay(recording.person)}</p>
                <p className="recording-start-time">{dayjs(recording.start_time).fromNow()}</p>
            </div>
            <span className="recording-duration">{humanFriendlyDuration(recording.recording_duration)}</span>
            <IconPlayCircle style={{ fontSize: '1.25rem' }} />
        </LemonButton>
    )
}

export function RecentRecordings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const sessionRecordingsTableLogicInstance = sessionRecordingsTableLogic({ key: 'projectHomepage' })
    const { sessionRecordingId, sessionRecordings, sessionRecordingsResponseLoading } = useValues(
        sessionRecordingsTableLogicInstance
    )
    const { closeSessionPlayer } = useActions(sessionRecordingsTableLogicInstance)

    return (
        <>
            {!!sessionRecordingId && <SessionPlayerDrawer onClose={closeSessionPlayer} />}
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
                              buttonHref: 'https://posthog.com/docs/user-guides/recordings',
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
