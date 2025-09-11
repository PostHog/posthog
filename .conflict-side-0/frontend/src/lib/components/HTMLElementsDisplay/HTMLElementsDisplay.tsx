import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { htmlElementsDisplayLogic } from 'lib/components/HTMLElementsDisplay/htmlElementsDisplayLogic'
import { ParsedCSSSelector } from 'lib/components/HTMLElementsDisplay/preselectWithCSS'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { ElementType } from '~/types'

import { Fade } from '../Fade/Fade'
import { SelectableElement } from './SelectableElement'

function indent(level: number): string {
    return Array(level).fill('    ').join('')
}

function CloseAllTags({
    elements,
    size = 'small',
}: {
    elements: ElementType[]
    size?: 'small' | 'xsmall'
}): JSX.Element {
    return (
        <>
            {[...elements]
                .reverse()
                .slice(1)
                .map((element, index) => (
                    <Fade
                        key={`${element.tag_name}-close-tags-${index}`}
                        visible={true}
                        style={{
                            position: 'static',
                        }}
                    >
                        <pre
                            className={clsx(
                                'whitespace-pre-wrap break-all !p-0 !m-0 rounded-none text-primary',
                                size === 'xsmall' ? 'text-xs' : 'text-sm'
                            )}
                            key={index}
                        >
                            {indent(elements.length - index - 2)}
                            &lt;/{element.tag_name}&gt;
                        </pre>
                    </Fade>
                ))}
        </>
    )
}

function Tags({
    elements,
    parsedCSSSelectors,
    highlight,
    editable,
    onChange,
    selectedText,
    size = 'small',
}: {
    elements: ElementType[]
    parsedCSSSelectors: Record<number, ParsedCSSSelector>
    highlight: boolean
    editable: boolean
    onChange: (i: number, s: ParsedCSSSelector) => void
    selectedText?: string
    size?: 'small' | 'xsmall'
}): JSX.Element {
    return (
        <>
            {elements.map((element, index) => {
                const reverseIndex = elements.length - 1 - index

                return (
                    <Fade
                        key={`${element.tag_name}-${reverseIndex}`}
                        visible={true}
                        style={{
                            position: 'static',
                        }}
                    >
                        <SelectableElement
                            key={`${element.tag_name}-${index}`}
                            element={element}
                            isDeepestChild={index === elements.length - 1}
                            onChange={(s) => (editable ? onChange(index, s) : undefined)}
                            readonly={!editable}
                            indent={indent(index)}
                            highlight={highlight}
                            parsedCSSSelector={parsedCSSSelectors[index]}
                            selectedText={selectedText}
                            size={size}
                        />
                    </Fade>
                )
            })}
        </>
    )
}

let uniqueNode = 0

interface HTMLElementsDisplayPropsBase {
    elements: ElementType[]
    highlight?: boolean
    selectedText?: string
    size?: 'small' | 'xsmall'
}

type HTMLElementsDisplayProps =
    | (HTMLElementsDisplayPropsBase & {
          editable: true
          // if provided the matching elements will be highlighted as a starting state
          startingSelector?: string
          checkUniqueness?: boolean
          onChange?: (selector: string, isUnique?: boolean) => void
          selectedText?: never
      })
    | (HTMLElementsDisplayPropsBase & {
          editable?: false
          startingSelector?: never
          checkUniqueness?: never
          onChange?: never
          selectedText?: string
      })

export function HTMLElementsDisplay({
    startingSelector,
    elements: providedElements,
    onChange,
    selectedText,
    highlight = true,
    editable = false,
    checkUniqueness = false,
    size = 'small',
}: HTMLElementsDisplayProps): JSX.Element {
    const [key] = useState(() => `HtmlElementsDisplay.${uniqueNode++}`)

    // can't have highlight and selectedText at the same time
    highlight = selectedText?.length ? false : highlight

    const logic = htmlElementsDisplayLogic({ checkUniqueness, onChange, key, startingSelector, providedElements })
    const {
        parsedSelectors,
        chosenSelector,
        chosenSelectorMatchCount,
        messageStatus,
        elementsToShowDepth,
        parsedElements,
    } = useValues(logic)
    const { setParsedSelectors, showAdditionalElements } = useActions(logic)

    return (
        <div className={clsx('flex flex-col gap-1', size === 'xsmall' && 'text-xxs')}>
            {editable && !!parsedElements.length && (
                <div className="flex flex-col gap-2 mb-2">
                    <div>Selector:</div>
                    <div className="w-full border rounded bg-primary px-4 py-2 select-text">
                        <pre className={clsx('m-0', size === 'xsmall' ? 'text-xxs' : 'text-sm')}>{chosenSelector}</pre>
                    </div>
                </div>
            )}
            {checkUniqueness && (
                // TODO use the SelectorCount element here?
                <LemonBanner type={messageStatus}>
                    {chosenSelectorMatchCount === null ? (
                        <>Choose parts of the HTML below to build a selector</>
                    ) : (
                        <>Matches: {chosenSelectorMatchCount} elements in the page</>
                    )}
                </LemonBanner>
            )}
            <div className="px-4 rounded bg-primary">
                {parsedElements.length ? (
                    <>
                        {elementsToShowDepth ? (
                            <pre
                                className={clsx(
                                    '!p-1 !m-0 opacity-50 text-primary cursor-pointer',
                                    size === 'xsmall' ? 'text-xxs' : 'text-sm'
                                )}
                                data-attr="elements-display-show-more-of-chain"
                                onClick={showAdditionalElements}
                            >
                                {`Show ${Math.min(3, elementsToShowDepth)} more parent${
                                    elementsToShowDepth > 1 ? 's' : ''
                                } (${elementsToShowDepth} hidden)`}
                            </pre>
                        ) : null}
                        <Tags
                            elements={parsedElements}
                            highlight={highlight}
                            editable={editable}
                            parsedCSSSelectors={parsedSelectors}
                            onChange={(index, s) => setParsedSelectors({ ...parsedSelectors, [index]: s })}
                            selectedText={selectedText}
                            size={size}
                        />
                        <CloseAllTags elements={parsedElements} size={size} />
                    </>
                ) : (
                    <div>No elements to display</div>
                )}
            </div>
        </div>
    )
}
