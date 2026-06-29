import { CSSProperties } from 'react'

export function uuid(): string {
    return '10000000-1000-4000-8000-100000000000'.replace(/[018]/g, (c) =>
        (
            parseInt(c) ^
            ((typeof window?.crypto !== 'undefined' // in node tests, jsdom doesn't implement window.crypto
                ? window.crypto.getRandomValues(new Uint8Array(1))[0]
                : Math.floor(Math.random() * 256)) &
                (15 >> (parseInt(c) / 4)))
        ).toString(16)
    )
}

export const selectStyle: Record<string, (base: Partial<CSSProperties>) => Partial<CSSProperties>> = {
    control: (base) => ({
        ...base,
        height: 31,
        minHeight: 31,
    }),
    indicatorsContainer: (base) => ({
        ...base,
        height: 31,
    }),
    input: (base) => ({
        ...base,
        paddingBottom: 0,
        paddingTop: 0,
        margin: 0,
        opacity: 1,
    }),
    valueContainer: (base) => ({
        ...base,
        padding: '0 8px',
        marginTop: -2,
    }),
    option: (base) => ({
        ...base,
        padding: '2px 15px',
    }),
}

export function clearDOMTextSelection(): void {
    if (window.getSelection) {
        if (window.getSelection()?.empty) {
            // Chrome
            window.getSelection()?.empty()
        } else if (window.getSelection()?.removeAllRanges) {
            // Firefox
            window.getSelection()?.removeAllRanges()
        }
    } else if ((document as any).selection) {
        // IE?
        ;(document as any).selection.empty()
    }
}

export function isMobile(): boolean {
    return navigator.userAgent.includes('Mobile')
}

export function isMac(): boolean {
    return navigator.platform.includes('Mac')
}

export function isWebKitBrowser(): boolean {
    // macOS Safari reports the Apple vendor. iOS forces every browser onto WebKit,
    // so also treat any iOS user agent as WebKit regardless of the vendor string it reports.
    return navigator.vendor === 'Apple Computer, Inc.' || /iPad|iPhone|iPod/.test(navigator.userAgent)
}

export function platformCommandControlKey(modifier: string): string {
    return `${isMac() ? '⌘' : 'Ctrl + '}${modifier}`
}

export function someParentMatchesSelector(element: HTMLElement, selector: string): boolean {
    if (element.matches(selector)) {
        return true
    }
    return element.parentElement ? someParentMatchesSelector(element.parentElement, selector) : false
}

export function downloadFile(file: File): void {
    // Create a link and set the URL using `createObjectURL`
    const link = document.createElement('a')
    link.style.display = 'none'
    link.href = URL.createObjectURL(file)
    link.download = file.name

    // It needs to be added to the DOM so it can be clicked
    document.body.appendChild(link)
    link.click()

    // To make this work on Firefox we need to wait
    // a little while before removing it.
    setTimeout(() => {
        URL.revokeObjectURL(link.href)
        link?.parentNode?.removeChild(link)
    }, 0)
}

export function inStorybookTestRunner(): boolean {
    return navigator.userAgent.includes('StorybookTestRunner')
}

export function inStorybook(): boolean {
    return '__STORYBOOK_CLIENT_API__' in window
}

export const shouldIgnoreInput = (e: KeyboardEvent): boolean => {
    return (
        ['input', 'textarea'].includes((e.target as HTMLElement).tagName.toLowerCase()) ||
        (e.target as HTMLElement).isContentEditable ||
        (e.target as HTMLElement).parentElement?.isContentEditable ||
        false
    )
}

/**
 * Uses the non-standard `memory` extension available in Chromium based browsers to
 * get JS heap metrics.
 */
export const getJSHeapMemory = (): {
    js_heap_used_mb?: number
    js_heap_total_mb?: number
    js_heap_limit_mb?: number
} => {
    if ('memory' in window.performance) {
        const memory = (window.performance as any).memory
        return {
            js_heap_used_mb: +(memory.usedJSHeapSize / 1024 / 1024).toFixed(2),
            js_heap_total_mb: +(memory.totalJSHeapSize / 1024 / 1024).toFixed(2),
            js_heap_limit_mb: +(memory.jsHeapSizeLimit / 1024 / 1024).toFixed(2),
        }
    }
    return {}
}
