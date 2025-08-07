import { ReactJsonViewProps } from '@microlink/react-json-view'
import { useEffect, useRef } from 'react'

import { JSONViewer } from './JSONViewer'

interface HighlightableJSONViewerProps extends ReactJsonViewProps {
    searchQuery?: string
}

export function HighlightableJSONViewer({ searchQuery, ...props }: HighlightableJSONViewerProps): JSX.Element {
    const containerRef = useRef<HTMLDivElement>(null)

    // Check if the JSON contains the search query to determine if we should expand it
    const shouldExpand =
        searchQuery?.trim() && JSON.stringify(props.src).toLowerCase().includes(searchQuery.toLowerCase().trim())

    // If there's a search match, expand more levels (or fully expand if collapsed is small)
    const effectiveCollapsed = shouldExpand
        ? typeof props.collapsed === 'number' && props.collapsed <= 5
            ? false
            : props.collapsed
        : props.collapsed

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
                    span.textContent = text.substring(foundIndex, foundIndex + query.length)
                    parts.push(span)

                    lastIndex = foundIndex + query.length
                    searchIndex = foundIndex + 1
                }

                if (lastIndex < text.length) {
                    parts.push(text.substring(lastIndex))
                }

                if (parts.length > 1) {
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
            if (nodesToProcess.length > 0) {
                // Find all collapsed sections and expand them if they contain highlights
                container.querySelectorAll('.collapsed-icon').forEach((collapsedIcon) => {
                    const parentElement = collapsedIcon.closest('.object-key-val') || collapsedIcon.parentElement
                    if (parentElement) {
                        // Check if this collapsed section or its siblings contain any highlights
                        const nextSibling = parentElement.nextElementSibling
                        if (nextSibling && nextSibling.querySelector('.search-highlight')) {
                            // Click the icon to expand it
                            ;(collapsedIcon as HTMLElement).click()
                        }
                    }
                })

                // Also check for react-json-view specific collapsed elements
                container.querySelectorAll('[class*="collapsed"]').forEach((element) => {
                    // Check if any parent has a highlight that we need to show
                    let parent = element.parentElement
                    while (parent && parent !== container) {
                        if (parent.querySelector('.search-highlight')) {
                            // Find and click the expand icon
                            const expandIcon = element.querySelector('.collapsed-icon, .expanded-icon, [class*="icon"]')
                            if (expandIcon && element.className.includes('collapsed')) {
                                ;(expandIcon as HTMLElement).click()
                            }
                            break
                        }
                        parent = parent.parentElement
                    }
                })
            }
        }

        // Apply highlights after ReactJson renders
        const timeoutId = setTimeout(applyHighlights, 50)
        return () => clearTimeout(timeoutId)
    }, [searchQuery, props.src])

    // Always wrap with ref for potential highlighting
    return (
        <div ref={containerRef}>
            <JSONViewer {...props} collapsed={effectiveCollapsed} />
        </div>
    )
}
