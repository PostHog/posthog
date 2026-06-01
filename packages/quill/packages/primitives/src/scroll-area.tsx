import { ScrollArea as ScrollAreaPrimitive } from '@base-ui/react/scroll-area'
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp } from 'lucide-react'
import * as React from 'react'

import { cn } from './lib/utils'
import './scroll-area.css'
import { Button } from './button'

type ScrollEdge = 'top' | 'right' | 'bottom' | 'left'
type ShowScrollToButton = ScrollEdge | 'all' | ReadonlyArray<ScrollEdge>

const ALL_EDGES: ReadonlyArray<ScrollEdge> = ['top', 'right', 'bottom', 'left']

function resolveEdges(value: ShowScrollToButton | undefined): ReadonlyArray<ScrollEdge> {
    if (!value) {
        return []
    }
    if (value === 'all') {
        return ALL_EDGES
    }
    if (Array.isArray(value)) {
        return value
    }
    return [value as ScrollEdge]
}

// Each button is gated on the Root having a matching base-ui overflow data attribute
// via Tailwind's `group-data-*` variants — no React state, no scroll listeners, no
// effects. Visibility is pure CSS driven by base-ui's internal scroll tracking.
const EDGE_CONFIG: Record<
    ScrollEdge,
    {
        label: string
        Icon: React.ComponentType<{ className?: string }>
        positionClasses: string
        visibleClasses: string
        getScrollTarget: (viewport: HTMLElement) => ScrollToOptions
    }
> = {
    top: {
        label: 'Scroll to top',
        Icon: ArrowUp,
        positionClasses: 'top-2 left-1/2 -translate-x-1/2',
        visibleClasses:
            'group-data-[overflow-y-start]/scroll-area:opacity-100 group-data-[overflow-y-start]/scroll-area:scale-100 group-data-[overflow-y-start]/scroll-area:pointer-events-auto',
        getScrollTarget: () => ({ top: 0 }),
    },
    bottom: {
        label: 'Scroll to bottom',
        Icon: ArrowDown,
        positionClasses: 'bottom-2 left-1/2 -translate-x-1/2',
        visibleClasses:
            'group-data-[overflow-y-end]/scroll-area:opacity-100 group-data-[overflow-y-end]/scroll-area:scale-100 group-data-[overflow-y-end]/scroll-area:pointer-events-auto',
        getScrollTarget: (viewport) => ({ top: viewport.scrollHeight }),
    },
    left: {
        label: 'Scroll to start',
        Icon: ArrowLeft,
        positionClasses: 'left-2 top-1/2 -translate-y-1/2 not-disabled:active:-translate-y-1/2',
        visibleClasses:
            'group-data-[overflow-x-start]/scroll-area:opacity-100 group-data-[overflow-x-start]/scroll-area:scale-100 group-data-[overflow-x-start]/scroll-area:pointer-events-auto',
        getScrollTarget: () => ({ left: 0 }),
    },
    right: {
        label: 'Scroll to end',
        Icon: ArrowRight,
        positionClasses: 'right-2 top-1/2 -translate-y-1/2 not-disabled:active:-translate-y-1/2',
        visibleClasses:
            'group-data-[overflow-x-end]/scroll-area:opacity-100 group-data-[overflow-x-end]/scroll-area:scale-100 group-data-[overflow-x-end]/scroll-area:pointer-events-auto',
        getScrollTarget: (viewport) => ({ left: viewport.scrollWidth }),
    },
}

function ScrollToEdgeButton({
    edge,
    viewportRef,
}: {
    edge: ScrollEdge
    viewportRef: React.RefObject<HTMLDivElement | null>
}): React.ReactElement {
    const config = EDGE_CONFIG[edge]
    const { Icon } = config
    const handleClick = (): void => {
        const viewport = viewportRef.current
        if (!viewport) {
            return
        }
        const prefersReducedMotion =
            typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
        viewport.scrollTo({
            ...config.getScrollTarget(viewport),
            behavior: prefersReducedMotion ? 'auto' : 'smooth',
        })
    }
    return (
        <Button
            type="button"
            size="icon"
            variant="outline"
            aria-label={config.label}
            onClick={handleClick}
            className={cn(
                'bg-background not-disabled:hover:bg-fill-hover absolute z-10 grid place-items-center rounded-full shadow-md',
                'opacity-0 scale-95 pointer-events-none',
                'transition-[opacity,transform,background-color] duration-150 ease-out',
                'motion-reduce:transition-none',
                'focus-visible:opacity-100 focus-visible:scale-100 focus-visible:pointer-events-auto',
                config.positionClasses,
                config.visibleClasses
            )}
        >
            <Icon className="size-4" />
        </Button>
    )
}

// Base-UI sets data-overflow-{x,y}-{start,end} attributes on the Root when the
// viewport has scrollable content remaining in that direction. Two pseudos on Root
// (::before = start edges left+top, ::after = end edges right+bottom) each stack two
// inset box-shadows driven by CSS custom properties, toggled via the data attrs.
// Injected once at module load rather than authored as Tailwind arbitrary values —
// the box-shadow syntax with nested commas and var() interactions is unreliable in
// Tailwind's arbitrary-property parser.
//
// Both the CSS string and ID are exported so consumers with strict CSP (nonce-based
// style-src) can inject themselves via `<style nonce={...}>{scrollShadowsCss}</style>`
// before the default auto-injection runs. Match the ID to dedupe.
export const SCROLL_SHADOWS_STYLE_ID = 'quill-scroll-area-shadows'
export const scrollShadowsCss = `
[data-component="scroll-area"][data-scroll-shadows="true"] {
    --shadow-x-start: 0 0 0 0 transparent;
    --shadow-x-end: 0 0 0 0 transparent;
    --shadow-y-start: 0 0 0 0 transparent;
    --shadow-y-end: 0 0 0 0 transparent;
}
[data-component="scroll-area"][data-scroll-shadows="true"][data-overflow-x-start] {
    --shadow-x-start: 16px 0 16px -16px rgb(0 0 0 / 25%);
}
[data-component="scroll-area"][data-scroll-shadows="true"][data-overflow-x-end] {
    --shadow-x-end: -16px 0 16px -16px rgb(0 0 0 / 25%);
}
[data-component="scroll-area"][data-scroll-shadows="true"][data-overflow-y-start] {
    --shadow-y-start: 0 16px 16px -16px rgb(0 0 0 / 25%);
}
[data-component="scroll-area"][data-scroll-shadows="true"][data-overflow-y-end] {
    --shadow-y-end: 0 -16px 16px -16px rgb(0 0 0 / 25%);
}
[data-component="scroll-area"][data-scroll-shadows="true"]::before,
[data-component="scroll-area"][data-scroll-shadows="true"]::after {
    content: '';
    position: absolute;
    inset: 0;
    pointer-events: none;
    z-index: 2;
    border-radius: inherit;
    transition: box-shadow 200ms ease;
}
[data-component="scroll-area"][data-scroll-shadows="true"]::before {
    box-shadow: var(--shadow-x-start) inset, var(--shadow-y-start) inset;
}
[data-component="scroll-area"][data-scroll-shadows="true"]::after {
    box-shadow: var(--shadow-x-end) inset, var(--shadow-y-end) inset;
}
.dark [data-component="scroll-area"][data-scroll-shadows="true"][data-overflow-x-start] {
    --shadow-x-start: 28px 0 24px -16px rgb(0 0 0 / 100%);
}
.dark [data-component="scroll-area"][data-scroll-shadows="true"][data-overflow-x-end] {
    --shadow-x-end: -28px 0 24px -16px rgb(0 0 0 / 100%);
}
.dark [data-component="scroll-area"][data-scroll-shadows="true"][data-overflow-y-start] {
    --shadow-y-start: 0 28px 24px -16px rgb(0 0 0 / 100%);
}
.dark [data-component="scroll-area"][data-scroll-shadows="true"][data-overflow-y-end] {
    --shadow-y-end: 0 -28px 24px -16px rgb(0 0 0 / 100%);
}
`

if (typeof document !== 'undefined' && !document.getElementById(SCROLL_SHADOWS_STYLE_ID)) {
    const styleEl = document.createElement('style')
    styleEl.id = SCROLL_SHADOWS_STYLE_ID
    styleEl.textContent = scrollShadowsCss
    document.head.appendChild(styleEl)
}

function ScrollArea({
    className,
    children,
    scrollShadows = true,
    hideScrollbars = false,
    alwaysShowScrollbars = false,
    showScrollToButton,
    ...props
}: ScrollAreaPrimitive.Root.Props & {
    scrollShadows?: boolean
    hideScrollbars?: boolean
    alwaysShowScrollbars?: boolean
    showScrollToButton?: ShowScrollToButton
}): React.ReactElement {
    const viewportRef = React.useRef<HTMLDivElement | null>(null)
    const edges = resolveEdges(showScrollToButton)
    if (process.env.NODE_ENV !== 'production' && hideScrollbars && alwaysShowScrollbars) {
        // eslint-disable-next-line no-console
        console.warn(
            '[ScrollArea] `hideScrollbars` and `alwaysShowScrollbars` are mutually exclusive; `alwaysShowScrollbars` will be ignored.'
        )
    }
    return (
        <ScrollAreaPrimitive.Root
            data-quill
            data-slot="scroll-area"
            // Just to keep around so we know it's a scroll area in case we merge props with another component
            data-component="scroll-area"
            data-scroll-shadows={scrollShadows}
            className={cn('quill-scroll-area group/scroll-area', className)}
            {...props}
        >
            <ScrollAreaPrimitive.Viewport
                ref={viewportRef}
                data-slot="scroll-area-viewport"
                className="quill-scroll-area__viewport"
            >
                {children}
            </ScrollAreaPrimitive.Viewport>
            {!hideScrollbars && (
                <>
                    <ScrollBar orientation="horizontal" alwaysVisible={alwaysShowScrollbars} />
                    <ScrollBar orientation="vertical" alwaysVisible={alwaysShowScrollbars} />
                    <ScrollAreaPrimitive.Corner data-slot="scroll-area-corner" className="quill-scroll-area__corner" />
                </>
            )}
            {edges.map((edge) => (
                <ScrollToEdgeButton key={edge} edge={edge} viewportRef={viewportRef} />
            ))}
        </ScrollAreaPrimitive.Root>
    )
}

function ScrollBar({
    className,
    orientation = 'vertical',
    alwaysVisible = false,
    ...props
}: ScrollAreaPrimitive.Scrollbar.Props & { alwaysVisible?: boolean }): React.ReactElement {
    return (
        <ScrollAreaPrimitive.Scrollbar
            data-slot="scroll-area-scrollbar"
            data-orientation={orientation}
            orientation={orientation}
            className={cn(
                'quill-scroll-area__scrollbar group/scrollbar flex',
                alwaysVisible ? 'quill-scroll-area__scrollbar--always' : 'quill-scroll-area__scrollbar--auto',
                className
            )}
            {...props}
        >
            <ScrollAreaPrimitive.Thumb data-slot="scroll-area-thumb" className="quill-scroll-area__thumb" />
        </ScrollAreaPrimitive.Scrollbar>
    )
}

export { ScrollArea, ScrollBar }
