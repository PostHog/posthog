import React from 'react'

import { IconAI, IconWarning } from '@posthog/icons'

import ViewRecordingButton, { RecordingPlayerType } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconLink } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { createActionFromEvent } from 'scenes/activity/explore/createActionFromEvent'
import { insightUrlForEvent } from 'scenes/insights/utils'
import { ArchiveSurveyButton } from 'scenes/surveys/components/ArchiveSurveyButton'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { EventType, SurveyEventName } from '~/types'

export function eventRowActionsContent(event: EventType): JSX.Element {
    const insightUrl = insightUrlForEvent(event)

    return (
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
            {event.event === SurveyEventName.SENT && event.uuid && event.properties.$survey_id ? (
                <ArchiveSurveyButton surveyId={event.properties.$survey_id} responseUuid={event.uuid} />
            ) : null}
            {event.uuid && event.timestamp && <EventCopyLinkButton event={event} />}
            <ViewRecordingButton
                fullWidth
                openPlayerIn={RecordingPlayerType.NewTab}
                sessionId={event.properties.$session_id}
                recordingStatus={event.properties.$recording_status}
                timestamp={event.timestamp}
                hasRecording={event.properties.has_recording as boolean | undefined}
                data-attr="events-table-view-recordings"
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
            {event.event === '$ai_trace' && '$ai_trace_id' in event.properties ? (
                <LemonButton
                    fullWidth
                    sideIcon={<IconAI />}
                    data-attr="events-table-trace-link"
                    to={urls.llmAnalyticsTrace(event.properties.$ai_trace_id, {
                        event: event.id,
                        exception_ts: event.timestamp,
                    })}
                >
                    View LLM Trace
                </LemonButton>
            ) : null}
            {insightUrl && (
                <LemonButton to={insightUrl} fullWidth data-attr="events-table-usage" targetBlank>
                    Try out in Insights
                </LemonButton>
            )}
        </>
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
