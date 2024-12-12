import ViewRecordingButton, { mightHaveRecording } from 'lib/components/ViewRecordingButton'
import { IconLink } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { createActionFromEvent } from 'scenes/activity/explore/createActionFromEvent'
import { insightUrlForEvent } from 'scenes/insights/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { EventType } from '~/types'

interface EventActionProps {
    event: EventType
}

export function EventRowActions({ event }: EventActionProps): JSX.Element {
    const insightUrl = insightUrlForEvent(event)

    return (
        <More
            overlay={
                <>
                    {getCurrentTeamId() && (
                        <LemonButton
                            onClick={() =>
                                void createActionFromEvent(
                                    getCurrentTeamId(),
                                    event,
                                    0,
                                    teamLogic.findMounted()?.values.currentTeam?.data_attributes || []
                                )
                            }
                            fullWidth
                            data-attr="events-table-create-action"
                        >
                            Create action from event
                        </LemonButton>
                    )}
                    {event.uuid && event.timestamp && (
                        <LemonButton
                            fullWidth
                            sideIcon={<IconLink />}
                            data-attr="events-table-event-link"
                            onClick={() =>
                                void copyToClipboard(
                                    urls.absolute(urls.currentProject(urls.event(String(event.uuid), event.timestamp))),
                                    'link to event'
                                )
                            }
                        >
                            Copy link to event
                        </LemonButton>
                    )}
                    <ViewRecordingButton
                        fullWidth
                        inModal
                        sessionId={event.properties.$session_id}
                        timestamp={event.timestamp}
                        disabledReason={
                            mightHaveRecording(event.properties)
                                ? undefined
                                : 'Replay was not active when capturing this event'
                        }
                        data-attr="events-table-usage"
                    />
                    {insightUrl && (
                        <LemonButton to={insightUrl} fullWidth data-attr="events-table-usage">
                            Try out in Insights
                        </LemonButton>
                    )}
                </>
            }
        />
    )
}
