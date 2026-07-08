import type React from 'react'

export interface LinkDragProps {
    elementProps: Pick<React.HTMLAttributes<HTMLElement>, 'onDragStart' | 'onDragEnd'>
}

export type UseLinkDragHook = (href: string | undefined) => LinkDragProps

const useNoopLinkDrag: UseLinkDragHook = () => ({ elementProps: {} })

let useLinkDragHook: UseLinkDragHook = useNoopLinkDrag

/**
 * Replaces the hook `Link` uses to make anchors draggable. The app registers the
 * drag-to-notebook implementation in `bootApp()`; bundles without notebooks (toolbar,
 * exporter) keep the inert default. Must be called before the first `Link` renders:
 * the implementation is read during render, and swapping it while Links are mounted
 * would violate the rules of hooks.
 */
export function setLinkDragHook(hook: UseLinkDragHook): void {
    useLinkDragHook = hook
}

export function useLinkDrag(href: string | undefined): LinkDragProps {
    return useLinkDragHook(href)
}
