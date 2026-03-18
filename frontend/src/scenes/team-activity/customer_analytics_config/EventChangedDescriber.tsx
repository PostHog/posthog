import { ActionsNode, EventsNode, NodeKind } from '~/queries/schema/schema-general'

export const EventChangedDescriber = ({
    eventType,
    beforeConfig,
    afterConfig,
}: {
    eventType: string
    beforeConfig: EventsNode | ActionsNode
    afterConfig: EventsNode | ActionsNode
}): JSX.Element => {
    const beforeDescription = getEventDescription(beforeConfig)
    const afterDescription = getEventDescription(afterConfig)

    return (
        <>
            changed <strong>{eventType}</strong> from <code>{beforeDescription}</code> to{' '}
            <code>{afterDescription}</code>
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
