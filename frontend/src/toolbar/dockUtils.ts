// Set transform and other style attributes on <body> and <html>
export function applyDockBodyStyles(
    htmlStyle: CSSStyleDeclaration,
    bodyStyle: CSSStyleDeclaration,
    zoom: number,
    padding: number,
    deferTransform = false
): void {
    // dark mode:
    // htmlStyle.background = 'hsl(231, 17%, 22%)'
    htmlStyle.background = 'linear-gradient(to right, hsla(234, 17%, 94%, 1) 71%, hsla(234, 17%, 99%, 1) 100%)'
    bodyStyle.boxShadow = 'hsl(219, 14%, 76%) 30px 30px 70px, hsl(219, 14%, 76%) 8px 8px 10px'
    if (!bodyStyle.background && !bodyStyle.backgroundColor && !bodyStyle.backgroundImage) {
        // if body background is not set, set to white to avoid transparency
        bodyStyle.backgroundColor = 'white'
    }
    bodyStyle.width = `100vw`
    bodyStyle.height = `auto`
    bodyStyle.minHeight = `calc(${100 / zoom}% - ${(2 * padding) / zoom}px)`

    if (deferTransform) {
        // needed by the animation
        window.requestAnimationFrame(() => {
            bodyStyle.transform = `scale(${zoom}) translate(${padding / zoom}px, ${padding / zoom}px)`
        })
    } else {
        bodyStyle.transform = `scale(${zoom}) translate(${padding / zoom}px, ${padding / zoom}px)`
    }
}

let listener: () => void
export function attachDockScrollListener(zoom: number, padding: number): void {
    listener = function () {
        const bodyElements = [...((document.body.getElementsByTagName('*') as unknown) as HTMLElement[])]
        bodyElements
            .filter((x) => getComputedStyle(x, null).getPropertyValue('position') === 'fixed')
            .forEach((e) => {
                const h = (window.pageYOffset + (window.pageYOffset > padding ? -padding : 0)) / zoom
                e.style.marginTop = `${h}px`
                e.setAttribute('data-posthog-fix-fixed', 'yes')
            })

        const tweakedElements = [
            ...((document.querySelectorAll('[data-posthog-fix-fixed=yes]') as unknown) as HTMLElement[]),
        ]
        tweakedElements
            .filter((x) => getComputedStyle(x, null).getPropertyValue('position') !== 'fixed')
            .forEach((e) => {
                e.style.marginTop = '0'
            })
    }
    window.addEventListener('scroll', listener)
}

export function removeDockScrollListener(): void {
    window.removeEventListener('scroll', listener)
}

// Update CSS variables (--zoom, etc) in #dock-toolbar inside the shadow root
export function updateDockToolbarVariables(
    shadowRef: { current?: { shadowRoot: ShadowRoot } | null } | null,
    zoom: number,
    padding: number,
    sidebarWidth: number
): void {
    if (shadowRef?.current) {
        const toolbarDiv = shadowRef.current.shadowRoot.getElementById('dock-toolbar')
        if (toolbarDiv) {
            toolbarDiv.style.setProperty('--zoom', `${zoom}`)
            toolbarDiv.style.setProperty('--padding', `${padding}px`)
            toolbarDiv.style.setProperty('--sidebar-width', `${sidebarWidth}px`)
        }
    }
}
