import { EventType } from '../../types'
import clsx from 'clsx'

function indent(level: number): string {
    return Array(level).fill('    ').join('')
}

export function EventElements({ event }: { event: EventType }): JSX.Element {
    let elements = [...(event.elements || [])].reverse()
    elements = elements.slice(Math.max(elements.length - 10, 1))

    return (
        <div
            className="p-4 m-2 rounded"
            style={{
                backgroundColor: 'rgb(39, 40, 34)', // consistent with okaidia syntax highlighter color
            }}
        >
            {elements.map((element, index) => (
                <pre
                    className={clsx(
                        'p-0 m-0 rounded whitespace-pre-wrap break-all text-white text-sm',
                        index === elements.length - 1 ? 'bg-primary-light' : 'bg-transparent'
                    )}
                    key={index}
                >
                    {indent(index)}
                    &lt;{element.tag_name}
                    {element.attr_id && ` id="${element.attr_id}"`}
                    {Object.entries(element.attributes ?? {}).map(([key, value]) => (
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
