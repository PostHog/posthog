import './ProjectHomepage.scss'

import { IconInfo } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { CompactList } from 'lib/components/CompactList/CompactList'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyDuration } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { asDisplay } from 'scenes/persons/person-utils'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import {
    DEFAULT_RECORDING_FILTERS,
    sessionRecordingsPlaylistLogic,
} from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { PropertyFilterType, PropertyOperator, SessionRecordingType } from '~/types'

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
            subtitle={`activity score: ${recording.mouse_activity_count}`}
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

export function WatchNextPanel(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const sessionRecordingsListLogicInstance = sessionRecordingsPlaylistLogic({
        logicKey: 'projectHomepage',
        filters: {
            ...DEFAULT_RECORDING_FILTERS,
            order: 'mouse_activity_count',
            duration: [
                {
                    type: PropertyFilterType.Recording,
                    key: 'active_seconds',
                    value: 5,
                    operator: PropertyOperator.GreaterThanOrEqual,
                },
            ],
        },
    })
    const { sessionRecordings, sessionRecordingsResponseLoading } = useValues(sessionRecordingsListLogicInstance)

    return (
        <>
            <CompactList
                title={
                    <Tooltip title="A selection of the most interesting recent recordings">
                        <div className="flex gap-1">
                            <IconInfo />
                            <span>Watch next</span>
                        </div>
                    </Tooltip>
                }
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
                              description: 'Once recordings are enabled, recordings will display here.',
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
