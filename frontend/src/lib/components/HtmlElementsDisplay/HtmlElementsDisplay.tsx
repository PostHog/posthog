import { ElementType } from '~/types'
import clsx from 'clsx'
import { Fragment, useEffect, useMemo, useState } from 'react'
import './HtmlElementsDisplay.scss'

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

    const [lastBuiltSelector, setLastBuiltSelector] = useState('')

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
        const builtSelector = `${tagSelector}${idSelector}${attributeSelectors.join('')}${textSelector}`
        if (builtSelector !== lastBuiltSelector) {
            console.log('builtSelector', builtSelector, selectedParts)
            setLastBuiltSelector(builtSelector)
            onChange(builtSelector)
        }
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

export function HtmlElementsDisplay({
    elements: providedElements,
    highlight = true,
    editable = false,
}: {
    elements: ElementType[]
    highlight?: boolean
    editable?: boolean
}): JSX.Element {
    const [selectors, setSelectors] = useState({} as Record<number, string>)
    const [chosenSelector, setChosenSelector] = useState('')
    const [elements, setElements] = useState(providedElements)
    const [lastElements, setLastElements] = useState(providedElements)

    useEffect(() => {
        if (JSON.stringify(providedElements) !== JSON.stringify(lastElements)) {
            console.log('setting elements', { providedElements, lastElements })
            let elements = [...(providedElements || [])].reverse()
            elements = elements.slice(Math.max(elements.length - 10, 1))
            setElements(elements)
            setLastElements(providedElements)
        }
    }, [providedElements, lastElements])

    const elementChildren = useMemo(() => {
        console.log('elementChildren')
        return elements.map((element, index) => (
            <pre
                className={clsx(
                    'p-0 m-0 rounded whitespace-pre-wrap break-all text-white text-sm',
                    index === elements.length - 1 && highlight ? 'bg-primary-light' : 'bg-transparent'
                )}
                key={`${element.tag_name}-${index}`}
            >
                {indent(index)}
                <SelectableElement
                    element={element}
                    isDeepestChild={index === elements.length - 1}
                    onChange={(s) => (editable ? onChange(index, s) : () => {})}
                    readonly={!editable}
                />
            </pre>
        ))
    }, [elements])

    useEffect(() => {
        let lastKey = -2
        let chosenSelector = ''
        Object.keys(selectors)
            .map((k) => Number.parseInt(k))
            .sort()
            .forEach((key) => {
                const selector = selectors[key]
                if (!!selector.trim().length) {
                    if (lastKey === key - 1) {
                        chosenSelector += ` > ${selector}`
                    } else {
                        chosenSelector += ` ${selector}`
                    }
                }
                lastKey = key
            })

        console.log('boo', { selectors, chosenSelector })

        const resultingSelector = !!chosenSelector.trim().length ? chosenSelector : 'no selectors chosen'
        if (resultingSelector !== chosenSelector) {
            setChosenSelector(resultingSelector)
        }
    }, [selectors])

    return (
        <div>
            <div className="p-4 m-2 rounded bg-default">
                {elements.length ? elementChildren : <div className="text-muted-light">No elements to display</div>}
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
            {editable && !!elements.length && <div className="p-4">Selector: {chosenSelector}</div>}
        </div>
    )

    function onChange(index: number, s: string): void {
        console.log('onChange', { index, s })
        return setSelectors({ ...selectors, [index]: s })
    }
}
