import { ElementType } from '~/types'
import { useEffect, useState } from 'react'
import { SelectableElement } from './SelectableElement'
import { AlertMessage } from 'lib/lemon-ui/AlertMessage'

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
    onChange,
    highlight = true,
    editable = false,
    checkUniqueness = false,
}: {
    elements: ElementType[]
    highlight?: boolean
    editable?: boolean
    checkUniqueness?: boolean
    onChange?: (selector: string, isUnique?: boolean) => void
}): JSX.Element {
    let elements = [...(providedElements || [])].reverse()
    elements = elements.slice(Math.max(elements.length - 10, 1))

    const [selectors, setSelectors] = useState({} as Record<number, string>)
    const [chosenSelector, setChosenSelector] = useState('')

    const [selectorMatches, setSelectorMatches] = useState([] as HTMLElement[])

    useEffect(() => {
        let lastKey = -2
        let builtSelector = ''

        Object.keys(selectors)
            .map((k) => Number.parseInt(k))
            .sort()
            .forEach((key) => {
                const selector = selectors[key]
                if (!!selector.trim().length) {
                    if (lastKey === key - 1 && !!builtSelector.trim().length) {
                        builtSelector += ` > ${selector}`
                    } else {
                        builtSelector += ` ${selector}`
                    }
                }
                lastKey = key
            })

        builtSelector = !!builtSelector.trim().length ? builtSelector.trim() : 'no selectors chosen'
        let selectorMatchCount = -1
        if (builtSelector !== chosenSelector) {
            if (checkUniqueness && !!builtSelector) {
                try {
                    const newSelectorMatches: HTMLElement[] = Array.from(document.querySelectorAll(builtSelector))
                    selectorMatchCount = newSelectorMatches.length
                    setSelectorMatches(newSelectorMatches)
                } catch (e) {
                    console.error(e)
                    setSelectorMatches([])
                }
            }

            setChosenSelector(builtSelector)
            onChange?.(builtSelector, checkUniqueness ? selectorMatchCount === 1 : undefined)
        }
    }, [selectors, selectorMatches, checkUniqueness])

    return (
        <div className="flex flex-col gap-1">
            {editable && !!elements.length && <div className="px-4">Selector: {chosenSelector}</div>}
            {checkUniqueness && (
                // TODO use the SelectorCount element here?
                <AlertMessage
                    type={selectorMatches.length === 0 ? 'info' : selectorMatches.length === 1 ? 'success' : 'warning'}
                >
                    {selectorMatches.length === 0 && chosenSelector === 'no selectors chosen' ? (
                        <>Choose parts of the HTML below to build a selector</>
                    ) : (
                        <>Matches: {selectorMatches.length} elements in the page</>
                    )}
                </AlertMessage>
            )}
            <div className="px-4 rounded bg-default">
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
        </div>
    )
}
