import { useActions } from 'kea'
import { dayjs } from 'lib/dayjs'
import { IconLink, IconPlayCircle } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { getCurrentTeamId } from 'lib/utils/logics'
import { createActionFromEvent } from 'scenes/events/createActionFromEvent'
import { insightUrlForEvent } from 'scenes/insights/utils'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { EventType } from '~/types'

interface EventActionProps {
    event: EventType
}

export function EventRowActions({ event }: EventActionProps): JSX.Element {
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)
    const insightUrl = insightUrlForEvent(event)

    return (
        <More
            overlay={
                <>
                    {getCurrentTeamId() && (
                        <LemonButton
                            status="stealth"
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
                            status="stealth"
                            fullWidth
                            sideIcon={<IconLink />}
                            data-attr="events-table-event-link"
                            onClick={() =>
                                void copyToClipboard(
                                    `${window.location.origin}${urls.event(String(event.uuid), event.timestamp)}`,
                                    'link to event'
                                )
                            }
                        >
                            Copy link to event
                        </LemonButton>
                    )}
                    {!!event.properties?.$session_id && (
                        <LemonButton
                            status="stealth"
                            to={urls.replaySingle(event.properties.$session_id)}
                            disableClientSideRouting
                            onClick={(e) => {
                                e.preventDefault()
                                if (event.properties.$session_id) {
                                    openSessionPlayer(
                                        { id: event.properties.$session_id },
                                        dayjs(event.timestamp).valueOf()
                                    )
                                }
                            }}
                            fullWidth
                            sideIcon={<IconPlayCircle />}
                            data-attr="events-table-usage"
                        >
                            View recording
                        </LemonButton>
                    )}
                    {insightUrl && (
                        <LemonButton to={insightUrl} status="stealth" fullWidth data-attr="events-table-usage">
                            Try out in Insights
                        </LemonButton>
                    )}
                </>
            }
        />
    )
}
