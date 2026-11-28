import type { MouseEvent } from 'react'

// `Link` sits in the kernel layer and cannot import the shell, so the shell registers its click handler here.
export type LinkPeekHandler = (href: string, element: HTMLElement) => boolean

let handler: LinkPeekHandler | null = null

export function registerLinkPeekHandler(next: LinkPeekHandler): () => void {
    handler = next
    return () => {
        if (handler === next) {
            handler = null
        }
    }
}

export function claimLinkClick(to: string | unknown[] | undefined, event: MouseEvent<HTMLElement>): boolean {
    // Shift and Alt keep their browser meaning (new window, download), so only a plain click is offered.
    if (!handler || typeof to !== 'string' || event.shiftKey || event.altKey) {
        return false
    }
    return handler(to, event.currentTarget)
}
