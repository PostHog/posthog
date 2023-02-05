import { ElementType } from '~/types'
import { useEffect, useState } from 'react'
import './HtmlElementsDisplay.scss'
import { SelectableElement } from './SelectableElement'

function indent(level: number): string {
    return Array(level).fill('    ').join('')
}

function CloseAllTags({ elements }: { elements: ElementType[] }): JSX.Element {
    return (
        <>
            {[...elements]
                .reverse()
                .slice(1)
                .map((element, index) => (
                    <pre
                        className="whitespace-pre-wrap break-all bg-default-dark p-0 m-0 rounded-none text-white text-sm"
                        key={index}
                    >
                        {indent(elements.length - index - 2)}
                        &lt;/{element.tag_name}&gt;
                    </pre>
                ))}
        </>
    )
}

function Tags({
    elements,
    highlight,
    editable,
    onChange,
}: {
    elements: ElementType[]
    highlight: boolean
    editable: boolean
    onChange: (i: number, s: string) => void
}): JSX.Element {
    return (
        <>
            {elements.map((element, index) => {
                return (
                    <SelectableElement
                        key={`${element.tag_name}-${index}`}
                        element={element}
                        isDeepestChild={index === elements.length - 1}
                        onChange={(s) => (editable ? onChange(index, s) : undefined)}
                        readonly={!editable}
                        indent={indent(index)}
                        highlight={highlight}
                    />
                )
            })}
        </>
    )
}

export function HtmlElementsDisplay({
    elements: providedElements,
    highlight = true,
    editable = false,
}: {
    elements: ElementType[]
    highlight?: boolean
    editable?: boolean
}): JSX.Element {
    let elements = [...(providedElements || [])].reverse()
    elements = elements.slice(Math.max(elements.length - 10, 1))

    const [selectors, setSelectors] = useState({} as Record<number, string>)
    const [chosenSelector, setChosenSelector] = useState('')

    useEffect(() => {
        let lastKey = -2
        let builtSelector = ''
        Object.keys(selectors)
            .map((k) => Number.parseInt(k))
            .sort()
            .forEach((key) => {
                const selector = selectors[key]
                if (!!selector.trim().length) {
                    if (lastKey === key - 1) {
                        builtSelector += ` > ${selector}`
                    } else {
                        builtSelector += ` ${selector}`
                    }
                }
                lastKey = key
            })

        builtSelector = !!builtSelector.trim().length ? builtSelector : 'no selectors chosen'
        if (builtSelector !== chosenSelector) {
            setChosenSelector(builtSelector)
        }
    }, [selectors])

    return (
        <div>
            <div className="p-4 m-2 rounded bg-default">
                {elements.length ? (
                    <>
                        <Tags
                            elements={elements}
                            highlight={highlight}
                            editable={editable}
                            onChange={(index, s) => setSelectors({ ...selectors, [index]: s })}
                        />
                        <CloseAllTags elements={elements} />
                    </>
                ) : (
                    <div className="text-muted-light">No elements to display</div>
                )}
            </div>
            {editable && !!elements.length && <div className="p-4">Selector: {chosenSelector}</div>}
        </div>
    )
}
