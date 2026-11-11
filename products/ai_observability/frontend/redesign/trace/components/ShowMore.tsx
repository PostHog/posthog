import { ReactNode, useId, useLayoutEffect, useRef, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { scrollIntoNearest } from './scrollIntoNearest'
import { useShowsQuery } from './useShowsQuery'

export interface ShowMoreProps {
    children: ReactNode
    /** Content whose text shows this query is never cut, so the search highlights in it stay visible. */
    highlightQuery?: string | null
    className?: string
}

function useIsTallerThanWindow(content: HTMLElement | null): boolean {
    const [isTall, setIsTall] = useState(false)
    useLayoutEffect(() => {
        if (!content) {
            return
        }
        const measure = (): void => setIsTall(content.offsetHeight > window.innerHeight)
        measure()
        const observer = new ResizeObserver(measure)
        observer.observe(content)
        window.addEventListener('resize', measure)
        return () => {
            observer.disconnect()
            window.removeEventListener('resize', measure)
        }
    }, [content])
    return isTall
}

/** Cuts content taller than the window to half the window's height, with a "Show more" that shows the rest. */
export function ShowMore({ children, highlightQuery = null, className }: ShowMoreProps): JSX.Element {
    const containerRef = useRef<HTMLDivElement>(null)
    const [content, setContent] = useState<HTMLDivElement | null>(null)
    const [isExpanded, setIsExpanded] = useState(false)
    const scrollAfterCollapse = useRef(false)
    const contentId = useId()
    const isTall = useIsTallerThanWindow(content)
    const isForcedOpen = useShowsQuery(content, highlightQuery)
    const isCut = isTall && !isExpanded && !isForcedOpen

    // Opening a folded value inside asks to read it, so the content must not then be cut away under it.
    useLayoutEffect(() => {
        if (!content) {
            return
        }
        const expandOnOpen = (event: Event): void => {
            if (event.target instanceof HTMLDetailsElement && event.target.open) {
                setIsExpanded(true)
            }
        }
        // `toggle` does not bubble, so the listener catches it in the capture phase.
        content.addEventListener('toggle', expandOnOpen, true)
        return () => content.removeEventListener('toggle', expandOnOpen, true)
    }, [content])

    useLayoutEffect(() => {
        if (scrollAfterCollapse.current) {
            scrollAfterCollapse.current = false
            // The parent is the whole message, bubble or section, so its header comes back into view too.
            scrollIntoNearest(containerRef.current?.parentElement ?? null)
        }
    }, [isExpanded])

    const toggle = (): void => {
        scrollAfterCollapse.current = isExpanded
        setIsExpanded(!isExpanded)
    }

    return (
        <div ref={containerRef} className={cn('flex min-w-0 flex-col gap-1', className)}>
            {/* `clip`, unlike `hidden`, stops the trace search and the opening scroll from scrolling the cut part
                into view. Browser find still matches text in the cut part without showing it. */}
            <div
                id={contentId}
                className={cn(
                    isCut &&
                        'max-h-[50vh] overflow-clip [mask-image:linear-gradient(to_bottom,black_calc(100%_-_4rem),transparent)]'
                )}
                // Keyboard focus can reach a link in the cut part, so the content opens to show it.
                onFocus={isCut ? () => setIsExpanded(true) : undefined}
            >
                <div ref={setContent} className="flex min-w-0 flex-col gap-2">
                    {children}
                </div>
            </div>
            {isTall && !isForcedOpen ? (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    className="self-start"
                    onClick={toggle}
                    aria-expanded={isExpanded}
                    aria-controls={contentId}
                    data-attr={isExpanded ? 'trace-view-show-less' : 'trace-view-show-more'}
                >
                    {isExpanded ? 'Show less' : 'Show more'}
                </LemonButton>
            ) : null}
        </div>
    )
}
