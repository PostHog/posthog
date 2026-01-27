import { ActionsNode, EventsNode, NodeKind } from '~/queries/schema/schema-general'

export const ConfigurationRemovedDescriber = ({
    eventType,
    eventConfig,
}: {
    eventType: string
    eventConfig: EventsNode | ActionsNode
}): JSX.Element => {
    const eventDescription = getEventDescription(eventConfig)

    return (
        <>
            removed <strong>Customer analytics</strong> configuration for <strong>{eventType}</strong>:{' '}
            <code>{eventDescription}</code>
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
