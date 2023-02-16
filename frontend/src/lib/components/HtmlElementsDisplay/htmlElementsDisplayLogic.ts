import { actions, kea, reducers, path, props, listeners, key } from 'kea'

import type { htmlElementsDisplayLogicType } from './htmlElementsDisplayLogicType'

export interface HtmlElementDisplayLogicProps {
    checkUniqueness: boolean
    onChange?: (selector: string, isUnique?: boolean) => void
    key: string
}

export interface ChosenSelector {
    processedSelector: string
    selectorMatchCount: number | null
}

export const htmlElementsDisplayLogic = kea<htmlElementsDisplayLogicType>([
    path(['lib', 'components', 'HtmlElementsDisplay', 'htmlElementsDisplayLogic']),
    props({ checkUniqueness: true } as HtmlElementDisplayLogicProps),
    key((props) => props.key),
    actions({
        setSelectors: (selectors: Record<number, string>) => ({ selectors }),
        chooseSelector: (chosenSelector: { processedSelector: string; selectorMatchCount: number | null }) => ({
            chosenSelector,
        }),
    }),
    reducers({
        selectors: [
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
    }),
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
            console.log('calling onChange with ', chosenSelector)
            props.onChange?.(
                chosenSelector.processedSelector,
                props.checkUniqueness ? chosenSelector.selectorMatchCount === 1 : undefined
            )
        },
    })),
])
