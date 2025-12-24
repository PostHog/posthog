import { ActivityChange, ChangeMapping } from 'lib/components/ActivityLog/humanizeActivity'

import { CoreEvent } from '~/queries/schema/schema-general'

interface CoreEventsConfig {
    core_events: CoreEvent[]
}

export const coreEventsConfigurationDescriber = (change?: ActivityChange): ChangeMapping | null => {
    if (!change) {
        return null
    }

    const before = (change.before ?? { core_events: [] }) as CoreEventsConfig
    const after = (change.after ?? { core_events: [] }) as CoreEventsConfig

    const descriptions = describeCoreEventsChanges(before.core_events ?? [], after.core_events ?? [])

    if (descriptions.length === 0) {
        return null
    }

    return {
        description: descriptions,
    }
}

const describeCoreEventsChanges = (before: CoreEvent[], after: CoreEvent[]): JSX.Element[] => {
    const diff: Record<string, { before?: CoreEvent; after?: CoreEvent }> = {}

    for (const event of before) {
        diff[event.id] ||= {}
        diff[event.id].before = event
    }

    for (const event of after) {
        diff[event.id] ||= {}
        diff[event.id].after = event
    }

    const descriptions: JSX.Element[] = []

    for (const eventId in diff) {
        const { before: beforeEvent, after: afterEvent } = diff[eventId]

        if (beforeEvent && !afterEvent) {
            descriptions.push(
                <>
                    removed the core event <code>{beforeEvent.name}</code>
                </>
            )
        } else if (!beforeEvent && afterEvent) {
            descriptions.push(
                <>
                    added the core event <code>{afterEvent.name}</code> ({afterEvent.category})
                </>
            )
        } else if (beforeEvent && afterEvent) {
            if (beforeEvent.name !== afterEvent.name) {
                descriptions.push(
                    <>
                        renamed the core event <code>{beforeEvent.name}</code> to <code>{afterEvent.name}</code>
                    </>
                )
            }

            if (beforeEvent.category !== afterEvent.category) {
                descriptions.push(
                    <>
                        changed the category of core event <code>{afterEvent.name}</code> from{' '}
                        <code>{beforeEvent.category}</code> to <code>{afterEvent.category}</code>
                    </>
                )
            }

            if (beforeEvent.description !== afterEvent.description) {
                descriptions.push(
                    <>
                        updated the description of core event <code>{afterEvent.name}</code>
                    </>
                )
            }

            if (JSON.stringify(beforeEvent.filter) !== JSON.stringify(afterEvent.filter)) {
                descriptions.push(
                    <>
                        updated the filter configuration of core event <code>{afterEvent.name}</code>
                    </>
                )
            }
        }
    }

    return descriptions
}
