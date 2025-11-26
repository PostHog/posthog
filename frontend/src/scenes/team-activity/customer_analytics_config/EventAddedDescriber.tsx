import { ActionsNode, EventsNode, NodeKind } from '~/queries/schema/schema-general'

export const EventAddedDescriber = ({
    eventType,
    eventConfig,
}: {
    eventType: string
    eventConfig: EventsNode | ActionsNode
}): JSX.Element => {
    const eventDescription = getEventDescription(eventConfig)

    return (
        <>
            added <strong>{eventType}</strong>: <code>{eventDescription}</code>
        </>
    )
}

function getEventDescription(eventConfig: EventsNode | ActionsNode): string {
    if (eventConfig.kind === NodeKind.EventsNode) {
        return eventConfig.event || 'All events'
    } else if (eventConfig.kind === NodeKind.ActionsNode) {
        return `Action #${eventConfig.id}`
    }
    return 'Unknown'
}
