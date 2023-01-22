import { ChartDisplayType, EventType, InsightType, TrendsFilterType } from '~/types'
import { More } from 'lib/components/LemonButton/More'
import { LemonButton } from 'lib/components/LemonButton'
import { createActionFromEvent } from 'scenes/events/createActionFromEvent'
import { urls } from 'scenes/urls'
import { getCurrentTeamId } from 'lib/utils/logics'
import { teamLogic } from 'scenes/teamLogic'
import { IconPlayCircle } from 'lib/components/icons'
import { useActions } from 'kea'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'

interface EventActionProps {
    event: EventType
}

export function EventRowActions({ event }: EventActionProps): JSX.Element {
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)

    let insightParams: Partial<TrendsFilterType> | undefined
    if (event.event === '$pageview') {
        insightParams = {
            insight: InsightType.TRENDS,
            interval: 'day',
            display: ChartDisplayType.ActionsLineGraph,
            actions: [],
            events: [
                {
                    id: '$pageview',
                    name: '$pageview',
                    type: 'events',
                    order: 0,
                    properties: [
                        {
                            key: '$current_url',
                            value: event.properties.$current_url,
                            type: 'event',
                        },
                    ],
                },
            ],
        }
    } else if (event.event !== '$autocapture') {
        insightParams = {
            insight: InsightType.TRENDS,
            interval: 'day',
            display: ChartDisplayType.ActionsLineGraph,
            actions: [],
            events: [
                {
                    id: event.event,
                    name: event.event,
                    type: 'events',
                    order: 0,
                    properties: [],
                },
            ],
        }
    }

    return (
        <More
            overlay={
                <>
                    {getCurrentTeamId() && (
                        <LemonButton
                            status="stealth"
                            onClick={() =>
                                createActionFromEvent(
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
                    {!!event.properties?.$session_id && (
                        <LemonButton
                            status="stealth"
                            to={urls.sessionRecording(event.properties.$session_id)}
                            disableClientSideRouting
                            onClick={(e) => {
                                e.preventDefault()
                                if (event.properties.$session_id) {
                                    openSessionPlayer({
                                        id: event.properties.$session_id,
                                    })
                                }
                            }}
                            fullWidth
                            sideIcon={<IconPlayCircle />}
                            data-attr="events-table-usage"
                        >
                            View recording
                        </LemonButton>
                    )}
                    {insightParams && (
                        <LemonButton
                            status="stealth"
                            to={urls.insightNew(insightParams)}
                            fullWidth
                            data-attr="events-table-usage"
                        >
                            Try out in Insights
                        </LemonButton>
                    )}
                </>
            }
        />
    )
}
