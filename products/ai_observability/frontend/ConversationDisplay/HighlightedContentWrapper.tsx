import { useEffect, useRef } from 'react'

export interface ExpandSelector {
    selector: string
    shouldExpand: (element: Element, container: Element) => boolean
    expand: (element: Element) => void
}

interface HighlightedContentWrapperProps {
    children: React.ReactNode
    searchQuery?: string
    onExpand?: () => void
    expandSelectors?: ExpandSelector[]
    delay?: number
}

/**
 * A wrapper component that applies search highlighting to any rendered content.
 * Works by using DOM manipulation after the content is rendered.
 */
export function HighlightedContentWrapper({
    children,
    searchQuery,
    onExpand,
    expandSelectors,
    delay,
}: HighlightedContentWrapperProps): JSX.Element {
    const containerRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const container = containerRef.current
        if (!container) {
            return
        }

        // Always remove any existing highlights first
        const removeHighlights = (): void => {
            container.querySelectorAll('.search-highlight').forEach((el) => {
                const parent = el.parentNode
                if (parent) {
                    parent.replaceChild(document.createTextNode(el.textContent || ''), el)
                    parent.normalize()
                }
            })
        }

        // If no search query, just clean up and return
        if (!searchQuery?.trim()) {
            removeHighlights()
            return
        }

        const applyHighlights = (): void => {
            // Remove any existing highlights
            removeHighlights()

            const query = searchQuery.toLowerCase().trim()
            const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
                acceptNode: (node) => {
                    // Skip empty nodes
                    if (!node.textContent?.trim()) {
                        return NodeFilter.FILTER_REJECT
                    }

                    // Skip nodes that are already highlighted
                    if (node.parentElement?.classList.contains('search-highlight')) {
                        return NodeFilter.FILTER_REJECT
                    }

                    // Accept if contains search query
                    if (node.textContent.toLowerCase().includes(query)) {
                        return NodeFilter.FILTER_ACCEPT
                    }

                    return NodeFilter.FILTER_REJECT
                },
            })

            const nodesToProcess: Text[] = []
            let node: Node | null
            while ((node = walker.nextNode())) {
                nodesToProcess.push(node as Text)
            }

            let hasHighlights = false

            nodesToProcess.forEach((textNode) => {
                const text = textNode.textContent || ''
                const lowerText = text.toLowerCase()
                const parent = textNode.parentElement
                if (!parent) {
                    return
                }

                const parts: (string | HTMLElement)[] = []
                let lastIndex = 0
                let searchIndex = 0

                while (searchIndex < lowerText.length) {
                    const foundIndex = lowerText.indexOf(query, searchIndex)
                    if (foundIndex === -1) {
                        break
                    }

                    if (foundIndex > lastIndex) {
                        parts.push(text.substring(lastIndex, foundIndex))
                    }

                    const span = document.createElement('span')
                    span.className = 'search-highlight'
                    span.style.backgroundColor = 'var(--danger)'
                    span.style.color = 'white'
                    span.style.borderRadius = '2px'
                    span.style.padding = '0 2px'
                    // Preserve monospace font in code blocks
                    const isInCode = parent.tagName === 'CODE' || parent.closest('pre')
                    if (isInCode) {
                        span.style.fontFamily = 'inherit'
                    }
                    span.textContent = text.substring(foundIndex, foundIndex + query.length)
                    parts.push(span)
                    hasHighlights = true

                    lastIndex = foundIndex + query.length
                    searchIndex = foundIndex + 1
                }

                if (lastIndex < text.length) {
                    parts.push(text.substring(lastIndex))
                }

                if (parts.length > 0 && parts.some((part) => typeof part !== 'string')) {
                    const fragment = document.createDocumentFragment()
                    parts.forEach((part) => {
                        if (typeof part === 'string') {
                            fragment.appendChild(document.createTextNode(part))
                        } else {
                            fragment.appendChild(part)
                        }
                    })

                    parent.replaceChild(fragment, textNode)
                }
            })

            // After highlighting, expand any collapsed sections that contain highlights
            if (hasHighlights) {
                if (expandSelectors && expandSelectors.length > 0) {
                    // Use custom expand selectors
                    expandSelectors.forEach(({ selector, shouldExpand, expand }) => {
                        container.querySelectorAll(selector).forEach((element) => {
                            if (shouldExpand(element, container)) {
                                expand(element)
                            }
                        })
                    })
                } else {
                    // Default expand logic for XML and simple collapsed sections
                    container.querySelectorAll('.cursor-pointer').forEach((collapsible) => {
                        const dotsElement = collapsible.querySelector('.text-muted')
                        if (dotsElement && dotsElement.textContent === '...') {
                            // Click to expand
                            ;(dotsElement as HTMLElement).click()
                        }
                    })
                }

                // Call optional expand callback
                if (onExpand) {
                    onExpand()
                }
            }
        }

        // Apply highlights after child component renders
        // Use provided delay or default based on content type
        const defaultDelay = container.querySelector('.LemonMarkdown') ? 100 : 50
        const timeoutId = setTimeout(applyHighlights, delay ?? defaultDelay)
        return () => {
            clearTimeout(timeoutId)
        }
    }, [searchQuery, children, onExpand, expandSelectors, delay])

    return <div ref={containerRef}>{children}</div>
}
