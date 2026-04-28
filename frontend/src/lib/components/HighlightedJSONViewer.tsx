import { ReactJsonViewProps } from '@microlink/react-json-view'

import {
    ExpandSelector,
    HighlightedContentWrapper,
} from 'products/llm_analytics/frontend/ConversationDisplay/HighlightedContentWrapper'

import { JSONViewer } from './JSONViewer'

interface HighlightedJSONViewerProps extends ReactJsonViewProps {
    searchQuery?: string
}

// JSON-specific expand selectors for react-json-view
const jsonExpandSelectors: ExpandSelector[] = [
    {
        selector: '.collapsed-icon',
        shouldExpand: (element) => {
            const parentElement = element.closest('.object-key-val') || element.parentElement
            if (parentElement) {
                const nextSibling = parentElement.nextElementSibling
                return !!(nextSibling && nextSibling.querySelector('.search-highlight'))
            }
            return false
        },
        expand: (element) => {
            ;(element as HTMLElement).click()
        },
    },
    {
        selector: '[class*="collapsed"]',
        shouldExpand: (element, container) => {
            // Check if any parent has a highlight that we need to show
            let parent = element.parentElement
            while (parent && parent !== container) {
                if (parent.querySelector('.search-highlight')) {
                    return element.className.includes('collapsed')
                }
                parent = parent.parentElement
            }
            return false
        },
        expand: (element) => {
            const expandIcon = element.querySelector('.collapsed-icon, .expanded-icon, [class*="icon"]')
            if (expandIcon) {
                ;(expandIcon as HTMLElement).click()
            }
        },
    },
]

export function HighlightedJSONViewer({ searchQuery, ...props }: HighlightedJSONViewerProps): JSX.Element {
    // Check if the JSON contains the search query to determine if we should expand it
    const shouldExpand =
        searchQuery?.trim() && JSON.stringify(props.src).toLowerCase().includes(searchQuery.toLowerCase().trim())

    // If there's a search match, expand more levels (or fully expand if collapsed is small)
    const effectiveCollapsed = shouldExpand
        ? typeof props.collapsed === 'number' && props.collapsed <= 5
            ? false
            : props.collapsed
        : props.collapsed

    return (
        <HighlightedContentWrapper searchQuery={searchQuery} expandSelectors={jsonExpandSelectors} delay={50}>
            <JSONViewer {...props} collapsed={effectiveCollapsed} />
        </HighlightedContentWrapper>
    )
}
