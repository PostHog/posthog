import clsx from 'clsx'
import { useActions } from 'kea'

import { LemonSnack } from 'lib/lemon-ui/LemonSnack'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { humanFriendlyDuration } from 'lib/utils'
import { asDisplay } from 'scenes/persons/person-utils'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { sessionRecordingEventUsageLogic } from 'scenes/session-recordings/sessionRecordingEventUsageLogic'

import { SessionRecordingType } from '~/types'

import { ProjectHomePageCompactListItem } from '../../project-homepage/ProjectHomePageCompactListItem'

export interface RecordingRowProps {
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
    const { reportRecordingOpenedFromRecentRecordingList } = useActions(sessionRecordingEventUsageLogic)

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
                })
                reportRecordingOpenedFromRecentRecordingList()
            }}
        />
    )
}
