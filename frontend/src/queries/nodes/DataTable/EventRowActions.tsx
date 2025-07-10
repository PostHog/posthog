import { IconWarning } from '@posthog/icons'
import ViewRecordingButton, { mightHaveRecording } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { IconLink } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import React from 'react'
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
                                    teamLogic.findMounted()?.values.currentTeam?.data_attributes || [],
                                    'Unfiled/Actions'
                                )
                            }
                            fullWidth
                            data-attr="events-table-create-action"
                        >
                            Create action from event
                        </LemonButton>
                    )}
                    {event.uuid && event.timestamp && <EventCopyLinkButton event={event} />}
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
                    {event.event === '$exception' && '$exception_issue_id' in event.properties ? (
                        <LemonButton
                            fullWidth
                            sideIcon={<IconWarning />}
                            data-attr="events-table-issue-link"
                            to={urls.errorTrackingIssue(
                                event.properties.$exception_issue_id,
                                event.properties.$exception_fingerprint
                            )}
                        >
                            Visit issue
                        </LemonButton>
                    ) : null}
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

export const EventCopyLinkButton = React.forwardRef<
    HTMLButtonElement,
    { event: Pick<EventType, 'uuid' | 'timestamp'> }
>(function EventCopyLinkButton({ event }, ref) {
    return (
        <LemonButton
            ref={ref}
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
    )
})
