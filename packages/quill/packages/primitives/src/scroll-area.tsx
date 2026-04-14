import { ScrollArea as ScrollAreaPrimitive } from '@base-ui/react/scroll-area'
import * as React from 'react'

import { cn } from './lib/utils'

// Base-UI sets data-overflow-{x,y}-{start,end} attributes on the Root when the
// viewport has scrollable content remaining in that direction. Two pseudos on Root
// (::before = start edges left+top, ::after = end edges right+bottom) each stack two
// inset box-shadows driven by CSS custom properties, toggled via the data attrs.
// Injected once at module load rather than authored as Tailwind arbitrary values —
// the box-shadow syntax with nested commas and var() interactions is unreliable in
// Tailwind's arbitrary-property parser.
const SCROLL_SHADOWS_STYLE_ID = 'quill-scroll-area-shadows'
const scrollShadowsCss = `
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
    ...props
}: ScrollAreaPrimitive.Root.Props & {
    scrollShadows?: boolean
    hideScrollbars?: boolean
    alwaysShowScrollbars?: boolean
}): React.ReactElement {
    return (
        <ScrollAreaPrimitive.Root
            data-slot="scroll-area"
            // Just to keep around so we know it's a scroll area in case we merge props with another component
            data-component="scroll-area"
            data-scroll-shadows={scrollShadows}
            className={cn('relative', className)}
            {...props}
        >
            <ScrollAreaPrimitive.Viewport
                data-slot="scroll-area-viewport"
                className="size-full rounded-[inherit] transition-[color,box-shadow] outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-1"
            >
                {children}
            </ScrollAreaPrimitive.Viewport>
            {!hideScrollbars && (
                <>
                    <ScrollBar orientation="horizontal" alwaysVisible={alwaysShowScrollbars} />
                    <ScrollBar orientation="vertical" alwaysVisible={alwaysShowScrollbars} />
                    <ScrollAreaPrimitive.Corner
                        data-slot="scroll-area-corner"
                        className="bg-transparent rounded-br-sm z-1"
                    />
                </>
            )}
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
                'group/scrollbar bg-input/50 flex touch-none p-px transition-colors select-none z-1 rounded-sm',
                'data-[orientation=horizontal]:w-full data-[orientation=horizontal]:data-[has-overflow-y]:w-[calc(100%-0.625rem)] data-[orientation=horizontal]:h-2.5 data-[orientation=horizontal]:flex-row',
                'data-[orientation=vertical]:h-full data-[orientation=vertical]:data-[has-overflow-x]:h-[calc(100%-0.625rem)] data-[orientation=vertical]:w-2.5 data-[orientation=vertical]:flex-col',
                alwaysVisible
                    ? 'opacity-100 pointer-events-auto'
                    : 'opacity-0 transition-opacity pointer-events-none data-[hovering]:opacity-100 data-[hovering]:delay-0 data-[hovering]:pointer-events-auto data-[scrolling]:opacity-100 data-[scrolling]:duration-0 data-[scrolling]:pointer-events-auto',
                className
            )}
            {...props}
        >
            <ScrollAreaPrimitive.Thumb
                data-slot="scroll-area-thumb"
                className="relative rounded-sm bg-input group-data-[orientation=vertical]/scrollbar:w-full group-data-[orientation=horizontal]/scrollbar:h-full"
            />
        </ScrollAreaPrimitive.Scrollbar>
    )
}

export { ScrollArea, ScrollBar }
