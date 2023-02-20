import { actions, kea, key, path, props, propsChanged, reducers, selectors } from 'kea'

import type { htmlElementsDisplayLogicType } from './htmlElementsDisplayLogicType'
import { ElementType } from '~/types'
import { objectsEqual } from 'lib/utils'
import {
    ParsedCSSSelector,
    parsedSelectorToSelectorString,
    preselect,
} from 'lib/components/HTMLElementsDisplay/preselectWithCSS'
import { subscriptions } from 'kea-subscriptions'

export interface HtmlElementDisplayLogicProps {
    checkUniqueness: boolean
    onChange?: (selector: string, isUnique?: boolean) => void
    startingSelector?: string
    providedElements: ElementType[]
    key: string
}

export const elementsChain = (providedElements: ElementType[] | undefined): ElementType[] => {
    const safeElements = [...(providedElements || [])]
    return safeElements.reverse().slice(Math.max(safeElements.length - 10, 1))
}

export const htmlElementsDisplayLogic = kea<htmlElementsDisplayLogicType>([
    path(['lib', 'components', 'HtmlElementsDisplay', 'htmlElementsDisplayLogic']),
    props({ checkUniqueness: true } as HtmlElementDisplayLogicProps),
    key((props) => props.key),
    actions({
        setParsedSelectors: (selectors: Record<number, ParsedCSSSelector>) => ({ selectors }),
        // chooseSelector: (chosenSelector: ChosenSelector) => ({
        //     chosenSelector,
        // }),
        setElements: (providedElements: ElementType[]) => ({ providedElements }),
    }),
    reducers(({ props }) => ({
        elements: [
            elementsChain(props.providedElements),
            { setElements: (_, { providedElements }) => elementsChain(providedElements) },
        ],
        parsedSelectorsRaw: [
            {} as Record<number, ParsedCSSSelector>,
            {
                setParsedSelectors: (_, { selectors }) => selectors,
            },
        ],
        messageStatus: [
            'info' as 'info' | 'success' | 'warning',
            {
                chooseSelector: (_, { chosenSelector }) => {
                    return chosenSelector.selectorMatchCount === null
                        ? 'info'
                        : chosenSelector.selectorMatchCount === 1
                        ? 'success'
                        : 'warning'
                },
            },
        ],
    })),
    propsChanged(({ actions, props }, oldProps) => {
        if (props.providedElements && !objectsEqual(props.providedElements, oldProps.providedElements)) {
            actions.setElements(props.providedElements)
        }
    }),
    selectors(() => ({
        // each element in the chain has a parsed selector it uses to track which things are selected
        parsedSelectors: [
            (s) => [s.parsedSelectorsRaw, (_, props) => props.startingSelector, s.elements],
            (parsedSelectorsRaw, startingSelector, providedElements): Record<number, ParsedCSSSelector> =>
                startingSelector && Object.keys(parsedSelectorsRaw).length === 0
                    ? preselect(providedElements, startingSelector)
                    : parsedSelectorsRaw,
        ],
        // contains the selector string built from the parsed selectors
        chosenSelector: [
            (s) => [s.parsedSelectors],
            (parsedSelectors): string => {
                let lastKey = -2
                let builtSelector = ''

                Object.keys(parsedSelectors)
                    .map((k) => Number.parseInt(k))
                    .sort()
                    .forEach((key) => {
                        const selector = !!parsedSelectors[key]
                            ? parsedSelectorToSelectorString(parsedSelectors[key])
                            : ''
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

                return builtSelector
            },
        ],
        chosenSelectorMatchCount: [
            (s) => [s.chosenSelector, (_, props) => props.checkUniqueness],
            (chosenSelector, checkUniqueness): number | null => {
                let selectorMatchCount: number | null = null
                if (checkUniqueness && chosenSelector !== 'no selectors chosen') {
                    try {
                        selectorMatchCount = Array.from(document.querySelectorAll(chosenSelector)).length
                    } catch (e) {
                        console.error(e)
                        selectorMatchCount = 0
                    }
                }
                return selectorMatchCount
            },
        ],
    })),
    subscriptions(({ props, values }) => ({
        chosenSelector: (value: string, oldValue: string): void => {
            if (value !== oldValue) {
                props.onChange?.(value, props.checkUniqueness ? values.chosenSelectorMatchCount === 1 : undefined)
            }
        },
    })),
])
