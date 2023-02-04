import { ElementType } from '../../types'
import clsx from 'clsx'

function indent(level: number): string {
    return Array(level).fill('    ').join('')
}

export function EventElements({
    elements: providedElements,
    highlight = true,
}: {
    elements: ElementType[]
    highlight?: boolean
}): JSX.Element {
    let elements = [...(providedElements || [])].reverse()
    elements = elements.slice(Math.max(elements.length - 10, 1))

    return (
        <div className="p-4 m-2 rounded bg-default">
            {elements.length ? (
                elements.map((element, index) => (
                    <pre
                        className={clsx(
                            'p-0 m-0 rounded whitespace-pre-wrap break-all text-white text-sm',
                            index === elements.length - 1 && highlight ? 'bg-primary-light' : 'bg-transparent'
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
                ))
            ) : (
                <div className="text-muted-light">No elements to display</div>
            )}
            {[...elements]
                .reverse()
                .slice(1)
                .map((element, index) => (
                    // TODO: make use of CodeSnippet here
                    <pre
                        className="whitespace-pre-wrap break-all bg-default-dark p-0 m-0 rounded-none text-white text-sm"
                        key={index}
                    >
                        {indent(elements.length - index - 2)}
                        &lt;/{element.tag_name}&gt;
                    </pre>
                ))}
        </div>
    )
}
