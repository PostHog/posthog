import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { sortedKeys } from 'lib/utils'

export function EventJSON(props: { event: Record<string, any> }): JSX.Element {
    const { event, id, uuid, distinct_id, properties, elements, timestamp, person, ...otherProps } = props.event

    // const eventJson = event
    const newEvent = {
        ...(id ? { id } : null),
        ...(uuid ? { uuid } : null),
        // We're discarding "person" when it's a weirdly serialized foreign key (some old API might give a string with an email)
        ...(typeof person !== 'string' && typeof person !== 'undefined' ? { person } : null),
        timestamp,
        event,
        distinct_id,
        properties: sortedKeys(properties),
        ...(elements && elements.length > 0 ? { elements } : null),
        ...otherProps,
    }

    return <CodeSnippet language={Language.JSON}>{JSON.stringify(newEvent, null, 4)}</CodeSnippet>
}
