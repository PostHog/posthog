/**
 * Lets the app shell claim a plain click on an in-app link before the router navigates.
 * `Link` sits in the kernel layer and cannot import the shell, so the shell registers the handler here.
 * The handler returns true when it took the click, for example to open the item in a peek drawer.
 */
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

export function claimLinkClick(href: string, element: HTMLElement): boolean {
    return handler ? handler(href, element) : false
}
