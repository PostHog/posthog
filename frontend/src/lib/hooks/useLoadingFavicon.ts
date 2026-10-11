import { useEffect } from 'react'

const LOADING_FAVICON = '/static/icons/favicon-loading.svg'

export function useLoadingFavicon(isLoading: boolean): void {
    useEffect(() => {
        if (!isLoading) {
            return
        }

        const faviconLinks = Array.from(document.querySelectorAll<HTMLLinkElement>('link[rel~="icon"]'))
        const originalAttributes = new Map(
            faviconLinks.map((link) => [
                link,
                {
                    href: link.getAttribute('href'),
                    type: link.getAttribute('type'),
                },
            ])
        )

        faviconLinks.forEach((link) => {
            link.setAttribute('href', LOADING_FAVICON)
            link.setAttribute('type', 'image/svg+xml')
        })

        return () => {
            originalAttributes.forEach(({ href, type }, link) => {
                if (href === null) {
                    link.removeAttribute('href')
                } else {
                    link.setAttribute('href', href)
                }

                if (type === null) {
                    link.removeAttribute('type')
                } else {
                    link.setAttribute('type', type)
                }
            })
        }
    }, [isLoading])
}
