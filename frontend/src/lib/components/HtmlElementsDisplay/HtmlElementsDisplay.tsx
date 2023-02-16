import { ElementType } from '~/types'
import { SelectableElement } from './SelectableElement'
import { AlertMessage } from 'lib/lemon-ui/AlertMessage'
import { htmlElementsDisplayLogic } from 'lib/components/HtmlElementsDisplay/htmlElementsDisplayLogic'
import { useActions, useValues } from 'kea'
import { useState } from 'react'
import { CodeSnippet } from 'lib/components/CodeSnippet'

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

let uniqueNode = 0

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
    const [key] = useState(() => `HtmlElementsDisplay.${uniqueNode++}`)

    let elements = [...(providedElements || [])].reverse()
    elements = elements.slice(Math.max(elements.length - 10, 1))

    const logic = htmlElementsDisplayLogic({ checkUniqueness, onChange, key })
    const { selectors, chosenSelector, messageStatus } = useValues(logic)
    const { setSelectors } = useActions(logic)

    return (
        <div className="flex flex-col gap-1">
            {editable && !!elements.length && (
                <div>
                    Selector:{' '}
                    <CodeSnippet copyDescription={'chosen selector'}>{chosenSelector.processedSelector}</CodeSnippet>
                </div>
            )}
            {checkUniqueness && (
                // TODO use the SelectorCount element here?
                <AlertMessage type={messageStatus}>
                    {chosenSelector.selectorMatchCount === null ? (
                        <>Choose parts of the HTML below to build a selector</>
                    ) : (
                        <>Matches: {chosenSelector.selectorMatchCount} elements in the page</>
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
