import { ElementType } from '~/types'
import clsx from 'clsx'
import { Fragment, useEffect, useState } from 'react'
import './Elements.scss'

function indent(level: number): string {
    return Array(level).fill('    ').join('')
}

function SelectableElement({
    element,
    isDeepestChild,
    onChange,
    readonly,
}: {
    element: ElementType
    isDeepestChild: boolean
    onChange: (selector: string) => void
    readonly: boolean
}): JSX.Element {
    const [selectedParts, setSelectedParts] = useState({ tag: undefined, id: undefined } as Record<
        string,
        string | Set<string> | undefined
    >)

    useEffect(() => {
        const attributeSelectors = Object.entries(selectedParts).reduce((acc, [key, value]) => {
            if (value instanceof Set) {
                value.forEach((entry) => {
                    acc.push(`[${key}="${entry}"]`)
                })
            }
            return acc
        }, [] as string[])

        const tagSelector = selectedParts.tag ? selectedParts.tag : ''
        const idSelector = selectedParts.id ? `[id="${selectedParts.id}"]` : ''
        const textSelector = selectedParts.text ? `[text="${selectedParts.text}"]` : ''
        onChange(`${tagSelector}${idSelector}${attributeSelectors.join('')}${textSelector}`)
    }, [selectedParts])

    const hoverSelector = readonly ? '' : 'hover:underline'
    const htmlElementsSelector = clsx('HtmlElements decoration-primary-highlight', !readonly && 'cursor-pointer')

    return (
        <>
            &lt;
            <span
                onClick={() =>
                    !readonly && selectedParts.tag
                        ? setSelectedParts({ ...selectedParts, tag: undefined })
                        : setSelectedParts({ ...selectedParts, tag: element.tag_name })
                }
                className={clsx(htmlElementsSelector, selectedParts.tag ? 'HtmlElements__selected' : hoverSelector)}
            >
                {element.tag_name}
            </span>
            {element.attr_id && ' '}
            <span
                onClick={() => {
                    !readonly && selectedParts.id
                        ? setSelectedParts({ ...selectedParts, id: undefined })
                        : setSelectedParts({ ...selectedParts, id: element.attr_id })
                }}
                className={clsx(htmlElementsSelector, selectedParts.id ? 'HtmlElements__selected' : hoverSelector)}
            >
                {element.attr_id && `id="${element.attr_id}"`}
            </span>
            {Object.entries(element.attributes ?? {}).map(([key, value], i) => {
                const attrName: string = key.replace('attr__', '')
                const selectionContainer = selectedParts[attrName]
                const parts = value.split(' ').map((part, index) => {
                    const isSelected = selectionContainer instanceof Set && selectionContainer.has(part)
                    return (
                        <Fragment key={`${attrName}=${part}`}>
                            {index === 0 ? '' : ' '}
                            <span
                                onClick={() => {
                                    if (readonly) {
                                        return
                                    }
                                    if (!selectedParts[attrName]) {
                                        setSelectedParts({ ...selectedParts, [attrName]: new Set([part]) })
                                    } else {
                                        if (isSelected) {
                                            setSelectedParts({
                                                ...selectedParts,
                                                [attrName]: new Set(
                                                    Array.from(selectedParts[attrName] as Set<string>).filter(
                                                        (p) => p !== part
                                                    )
                                                ),
                                            })
                                        } else {
                                            setSelectedParts({
                                                ...selectedParts,
                                                [attrName]: new Set([
                                                    ...Array.from(selectedParts[attrName] as Set<string>),
                                                    part,
                                                ]),
                                            })
                                        }
                                    }
                                }}
                                className={clsx(
                                    htmlElementsSelector,
                                    isSelected ? 'HtmlElements__selected' : hoverSelector
                                )}
                            >
                                {part}
                            </span>
                        </Fragment>
                    )
                })
                return (
                    <Fragment key={`${key}-${i}`}>
                        {' '}
                        {attrName}="{parts}"
                    </Fragment>
                )
            })}
            &gt;
            <span
                onClick={() => {
                    if (readonly) {
                        return
                    }
                    if (selectedParts.text) {
                        setSelectedParts({ ...selectedParts, text: undefined })
                    } else {
                        setSelectedParts({ ...selectedParts, text: element.text })
                    }
                }}
                className={clsx(htmlElementsSelector, selectedParts.text ? 'HtmlElements__selected' : hoverSelector)}
            >
                {element.text}
            </span>
            {isDeepestChild && <span>&lt;/{element.tag_name}&gt;</span>}
        </>
    )
}

export function EventElements({
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

    function selectorFrom(selectors: Record<number, string>): string {
        let lastKey = -2
        let chosenSelector = ''
        Object.keys(selectors)
            .map((k) => Number.parseInt(k))
            .sort()
            .forEach((key) => {
                const selector = selectors[key]
                if (lastKey === key - 1) {
                    chosenSelector += ` > ${selector}`
                } else {
                    chosenSelector += ` ${selector}`
                }
                lastKey = key
            })

        return !!chosenSelector.trim().length ? chosenSelector : 'no selectors chosen'
    }

    return (
        <div>
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
                            <SelectableElement
                                element={element}
                                isDeepestChild={index === elements.length - 1}
                                onChange={(s) => (editable ? setSelectors({ ...selectors, [index]: s }) : () => {})}
                                readonly={!editable}
                            />
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
            {editable && <div className="p-4">Selector: {selectorFrom(selectors)}</div>}
        </div>
    )
}
