import './ProjectHomepage.scss'

import { IconInfo } from '@posthog/icons'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { CompactList } from 'lib/components/CompactList/CompactList'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyDuration } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { asDisplay } from 'scenes/persons/person-utils'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import {
    DEFAULT_RECORDING_FILTERS,
    defaultRecordingDurationFilter,
    sessionRecordingsPlaylistLogic,
} from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SessionRecordingType } from '~/types'

import { ProjectHomePageCompactListItem } from './ProjectHomePageCompactListItem'

interface RecordingRowProps {
    recording: SessionRecordingType
}

type ACTIVITY_DESCRIPTIONS = 'very low' | 'low' | 'medium' | 'high' | 'very high'

function ActivityScoreLabel({ score }: { score: number | undefined }): JSX.Element {
    const n = score ?? 0
    let backgroundColor = 'bg-primary-alt-highlight'
    let description: ACTIVITY_DESCRIPTIONS = 'very low'
    if (n >= 90) {
        backgroundColor = 'bg-success-highlight'
        description = 'very high'
    } else if (n >= 75) {
        backgroundColor = 'bg-success-highlight'
        description = 'high'
    } else if (n >= 50) {
        backgroundColor = 'bg-warning-highlight'
        description = 'medium'
    } else if (n >= 25) {
        backgroundColor = 'bg-warning-highlight'
        description = 'low'
    }

    return <LemonSnack className={clsx(backgroundColor, 'text-xs')}>activity: {description}</LemonSnack>
}

export function RecordingRow({ recording }: RecordingRowProps): JSX.Element {
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)
    const { reportRecordingOpenedFromRecentRecordingList } = useActions(eventUsageLogic)

    return (
        <ProjectHomePageCompactListItem
            title={asDisplay(recording.person)}
            subtitle={<ActivityScoreLabel score={recording.activity_score} />}
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

export interface WatchNextListProps {
    sessionRecordings: SessionRecordingType[]
    loading: boolean
    recordingsOptIn: boolean | undefined
}

// separated from the logics so that it can have storybook tests without mocking API calls
export function WatchNextList({ sessionRecordings, loading, recordingsOptIn }: WatchNextListProps): JSX.Element {
    return (
        <CompactList
            title={
                <Tooltip title="A selection of the most interesting recordings. We use multiple signals to calculate an activity score.">
                    <div className="flex items-center gap-1.5">
                        <span>Watch next</span>
                        <IconInfo className="text-lg" />
                    </div>
                </Tooltip>
            }
            viewAllURL={urls.replay()}
            loading={loading}
            emptyMessage={
                recordingsOptIn
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
            renderRow={(recording: SessionRecordingType, index) => <RecordingRow key={index} recording={recording} />}
        />
    )
}

export function WatchNextPanel(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const sessionRecordingsListLogicInstance = sessionRecordingsPlaylistLogic({
        logicKey: 'projectHomepage',
        filters: {
            ...DEFAULT_RECORDING_FILTERS,
            duration: [
                {
                    ...defaultRecordingDurationFilter,
                    value: 60,
                },
            ],
            date_to: '-15M',
            order: 'activity_score',
        },
    })
    const { sessionRecordings, sessionRecordingsResponseLoading } = useValues(sessionRecordingsListLogicInstance)

    return (
        <WatchNextList
            recordingsOptIn={currentTeam?.session_recording_opt_in}
            sessionRecordings={sessionRecordings}
            loading={sessionRecordingsResponseLoading}
        />
    )
}
