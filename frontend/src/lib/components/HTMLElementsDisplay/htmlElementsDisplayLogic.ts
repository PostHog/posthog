import { actions, kea, reducers, path, props, listeners, key, propsChanged } from 'kea'

import type { htmlElementsDisplayLogicType } from './htmlElementsDisplayLogicType'
import { ElementType } from '~/types'
import { objectsEqual } from 'lib/utils'

export interface HtmlElementDisplayLogicProps {
    checkUniqueness: boolean
    onChange?: (selector: string, isUnique?: boolean) => void
    startingSelector?: string
    providedElements: ElementType[]
    key: string
}

export interface ChosenSelector {
    processedSelector: string
    selectorMatchCount: number | null
}

const elementsChain = (providedElements: ElementType[]): ElementType[] =>
    [...(providedElements || [])].reverse().slice(Math.max(providedElements.length - 10, 1))

export const htmlElementsDisplayLogic = kea<htmlElementsDisplayLogicType>([
    path(['lib', 'components', 'HtmlElementsDisplay', 'htmlElementsDisplayLogic']),
    props({ checkUniqueness: true } as HtmlElementDisplayLogicProps),
    key((props) => props.key),
    actions({
        setSelectors: (selectors: Record<number, string>) => ({ selectors }),
        chooseSelector: (chosenSelector: { processedSelector: string; selectorMatchCount: number | null }) => ({
            chosenSelector,
        }),
        setElements: (providedElements: ElementType[]) => ({ providedElements }),
    }),
    reducers(({ props }) => ({
        elements: [
            elementsChain(props.providedElements),
            { setElements: (_, { providedElements }) => elementsChain(providedElements) },
        ],
        internallySetSelectors: [
            {},
            {
                setSelectors: (_, { selectors }) => selectors,
            },
        ],
        chosenSelector: [
            { processedSelector: 'No selectors chosen.', selectorMatchCount: null } as ChosenSelector,
            {
                chooseSelector: (_, { chosenSelector }) => chosenSelector,
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
    listeners(({ props, actions }) => ({
        setSelectors: ({ selectors }) => {
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

            let selectorMatchCount: number | null = null
            if (props.checkUniqueness && builtSelector !== 'no selectors chosen') {
                try {
                    selectorMatchCount = Array.from(document.querySelectorAll(builtSelector)).length
                } catch (e) {
                    console.error(e)
                    selectorMatchCount = 0
                }
            }

            actions.chooseSelector({ processedSelector: builtSelector, selectorMatchCount })
        },
        chooseSelector: ({ chosenSelector }) => {
            props.onChange?.(
                chosenSelector.processedSelector,
                props.checkUniqueness ? chosenSelector.selectorMatchCount === 1 : undefined
            )
        },
    })),
    propsChanged(({ actions, props }, oldProps) => {
        if (props.providedElements && !objectsEqual(props.providedElements, oldProps.providedElements)) {
            actions.setElements(props.providedElements)
        }
    }),
])
