import { useActions } from 'kea'
import { combineUrl } from 'kea-router'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { dayjs } from 'lib/dayjs'
import { IconLink, IconPlayCircle } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import {
    createActionFromEvent,
    createFilterFromEvent,
    MinimalEventFilterType,
} from 'scenes/events/createActionFromEvent'
import { insightUrlForEvent } from 'scenes/insights/utils'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { EventType, PipelineStage } from '~/types'

interface EventActionProps {
    event: EventType
    onAddFilter?: (filter: MinimalEventFilterType) => void
}

export function EventRowActions({ event, onAddFilter }: EventActionProps): JSX.Element {
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)
    const insightUrl = insightUrlForEvent(event)

    const eventFilters = createFilterFromEvent(event)

    return (
        <More
            overlay={
                <>
                    {getCurrentTeamId() && (
                        <>
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

                            {onAddFilter ? (
                                <LemonButton
                                    onClick={() => onAddFilter?.(eventFilters)}
                                    fullWidth
                                    data-attr="events-table-create-destination"
                                >
                                    Filter for similar events
                                </LemonButton>
                            ) : null}

                            <FlaggedFeature flag="plugins-filtering">
                                <LemonButton
                                    to={
                                        combineUrl(urls.pipelineNodeNew(PipelineStage.Destination), undefined, {
                                            configuration: JSON.stringify({
                                                filters: {
                                                    events: [
                                                        {
                                                            id: event.id,
                                                            type: 'events',
                                                            order: 0,
                                                            name: eventFilters.event,
                                                            properties: eventFilters.properties,
                                                        },
                                                    ],
                                                },
                                            }),
                                        }).url
                                    }
                                    fullWidth
                                    data-attr="events-table-create-destination"
                                >
                                    Create pipeline destination for event
                                </LemonButton>
                            </FlaggedFeature>
                        </>
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
                    {!!event.properties?.$session_id && (
                        <LemonButton
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
                        <LemonButton to={insightUrl} fullWidth data-attr="events-table-usage">
                            Try out in Insights
                        </LemonButton>
                    )}
                </>
            }
        />
    )
}
