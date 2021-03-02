import React from 'react'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'

function sortKeys(object: Record<string, any>): Record<string, any> {
    const newObject: Record<string, any> = {}
    for (const key of Object.keys(object).sort()) {
        newObject[key] = object[key]
    }
    return newObject
}

export function EventJSON(props: { event: Record<string, any> }): JSX.Element {
    const { event, id, uuid, distinct_id, properties, elements, timestamp, person, ...otherProps } = props.event

    // We're discarding "person", which is a weirdly serialized foreign key (the api gives a string with an email)
    void person

    // const eventJson = event
    const newEvent = {
        ...(id ? { id } : null),
        ...(uuid ? { uuid } : null),
        timestamp,
        event,
        distinct_id,
        properties: sortKeys(properties),
        ...(elements && elements.length > 0 ? { elements } : null),
        ...otherProps,
    }

    const eventJSON = JSON.stringify(newEvent, null, 4)

    return (
        <div>
            <CodeSnippet language={Language.JSON}>{eventJSON}</CodeSnippet>
        </div>
    )
}
