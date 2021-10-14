import React from 'react'
import { EventType } from '../../types'

function indent(level: number): string {
    return Array(level).fill('    ').join('')
}

export function EventElements({ event }: { event: EventType }): JSX.Element {
    let elements = [...(event.elements || [])].reverse()
    elements = elements.slice(Math.max(elements.length - 10, 1))

    return (
        <div>
            {elements.map((element, index) => (
                <pre
                    className="code"
                    key={index}
                    style={{
                        margin: 0,
                        padding: 0,
                        borderRadius: 0,
                        backgroundColor: index === elements.length - 1 ? 'var(--primary)' : undefined,
                    }}
                >
                    {indent(index)}
                    &lt;{element.tag_name}
                    {element.attr_id && ` id="${element.attr_id}"`}
                    {Object.entries(element.attributes).map(([key, value]) => (
                        <span key={key}>{` ${key.replace('attr__', '')}="${value}"`}</span>
                    ))}
                    &gt;{element.text}
                    {index === elements.length - 1 && <span>&lt;/{element.tag_name}&gt;</span>}
                </pre>
            ))}
            {[...elements]
                .reverse()
                .slice(1)
                .map((element, index) => (
                    // TODO: make use of CodeSnippet here
                    <pre className="code" key={index} style={{ margin: 0, padding: 0, borderRadius: 0 }}>
                        {indent(elements.length - index - 2)}
                        &lt;/{element.tag_name}&gt;
                    </pre>
                ))}
        </div>
    )
}
