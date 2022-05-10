import React from 'react'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'
import { sortedKeys } from 'lib/utils'

export function EventJSON(props: { event: Record<string, any> }): JSX.Element {
    const { event, id, uuid, distinct_id, properties, elements, timestamp, person, person_properties, ...otherProps } =
        props.event

    // We're discarding "person", which is a weirdly serialized foreign key (the api gives a string with an email)
    void person

    // const eventJson = event
    const newEvent = {
        ...(id ? { id } : null),
        ...(uuid ? { uuid } : null),
        timestamp,
        event,
        distinct_id,
        properties: sortedKeys(properties),
        ...(elements && elements.length > 0 ? { elements } : null),
        ...(person_properties && { person_properties: sortedKeys(person_properties) }),
        ...otherProps,
    }

    return <CodeSnippet language={Language.JSON}>{JSON.stringify(newEvent, null, 4)}</CodeSnippet>
}
