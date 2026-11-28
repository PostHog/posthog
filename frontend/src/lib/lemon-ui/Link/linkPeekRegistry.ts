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

export function claimLinkClick(href: string, element: HTMLElement): boolean {
    return handler ? handler(href, element) : false
}
