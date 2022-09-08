import React from 'react'
import { dayjs } from 'lib/dayjs'
import { useActions, useValues } from 'kea'

import './ProjectHomepage.scss'
import { CompactList } from 'lib/components/CompactList/CompactList'
import { LemonButton } from 'lib/components/LemonButton'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { asDisplay } from 'scenes/persons/PersonHeader'
import { sessionRecordingsTableLogic } from 'scenes/session-recordings/sessionRecordingsTableLogic'
import { urls } from 'scenes/urls'
import { SessionRecordingType } from '~/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { humanFriendlyDuration } from 'lib/utils'
import { IconPlayCircle } from 'lib/components/icons'
import { SessionPlayerDrawer } from 'scenes/session-recordings/SessionPlayerDrawer'
import { teamLogic } from 'scenes/teamLogic'
import { sessionPlayerDrawerLogic } from 'scenes/session-recordings/sessionPlayerDrawerLogic'

interface RecordingRowProps {
    recording: SessionRecordingType
}

function RecordingRow({ recording }: RecordingRowProps): JSX.Element {
    const sessionRecordingsTableLogicInstance = sessionRecordingsTableLogic({ key: 'projectHomepage' })
    const { openSessionPlayer } = useActions(sessionRecordingsTableLogicInstance)
    const { reportRecordingOpenedFromRecentRecordingList } = useActions(eventUsageLogic)

    return (
        <LemonButton
            fullWidth
            onClick={() => {
                openSessionPlayer(recording.id)
                reportRecordingOpenedFromRecentRecordingList()
            }}
        >
            <div className="ProjectHomePage__listrow">
                <ProfilePicture name={asDisplay(recording.person)} />

                <div className="ProjectHomePage__listrow__details">
                    <div>{asDisplay(recording.person)}</div>
                    <div>Recorded {dayjs(recording.start_time).fromNow()}</div>
                </div>

                <span>{humanFriendlyDuration(recording.recording_duration)}</span>
                <IconPlayCircle className="text-lg ml-2" />
            </div>
        </LemonButton>
    )
}

export function RecentRecordings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const sessionRecordingsTableLogicInstance = sessionRecordingsTableLogic({ key: 'projectHomepage' })
    const { sessionRecordings, sessionRecordingsResponseLoading } = useValues(sessionRecordingsTableLogicInstance)
    const { closeSessionPlayer } = useActions(sessionPlayerDrawerLogic)

    return (
        <>
            <SessionPlayerDrawer onClose={closeSessionPlayer} />
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
