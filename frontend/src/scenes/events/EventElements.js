import React from 'react'

function indent(n) {
    return Array(n)
        .fill('')
        .map((_, i) => <span key={i}>&nbsp;&nbsp;&nbsp;&nbsp;</span>)
}

export function EventElements({ event }) {
    const elements = [...event.elements].reverse()

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
                        ...(index === elements.length - 1 ? { backgroundColor: 'var(--blue)' } : {}),
                    }}
                >
                    {indent(index)}
                    &lt;{element.tag_name}
                    {element.attr_id && ' id="' + element.attr_id + '"'}
                    {Object.entries(element.attributes).map(([key, value]) => (
                        <span key={key}>
                            {' '}
                            {key.replace('attr__', '')}="{value}"
                        </span>
                    ))}
                    &gt;{element.text}
                    {index === elements.length - 1 && <span>&lt;/{element.tag_name}&gt;</span>}
                </pre>
            ))}
            {[...elements]
                .reverse()
                .slice(1)
                .map((element, index) => (
                    <pre className="code" key={index} style={{ margin: 0, padding: 0, borderRadius: 0 }}>
                        {indent(elements.length - index - 2)}
                        &lt;/{element.tag_name}&gt;
                    </pre>
                ))}
        </div>
    )
}
