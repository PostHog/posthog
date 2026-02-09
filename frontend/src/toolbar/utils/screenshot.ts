import { toBlob } from 'html-to-image'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { TOOLBAR_ID } from '~/toolbar/utils'

const allPropertyNames = (function getAllPropertyNames() {
    const names = []
    const style = getComputedStyle(document.documentElement)
    for (let i = 0; i < style.length; i++) {
        const name = style[i]
        if (!name.startsWith('--')) {
            names.push(name)
        }
    }
    return names
})()

function shouldIncludeNode(node: HTMLElement): boolean {
    // Exclude the toolbar from the screenshot
    return node.id !== TOOLBAR_ID
}

export async function captureScreenshot(): Promise<Blob | null> {
    try {
        const blob = await toBlob(document.body, {
            includeStyleProperties: allPropertyNames,
            quality: 0.4,
            filter: shouldIncludeNode,
        })
        if (!blob) {
            lemonToast.error('Could not take screenshot. Please try again.')
            return null
        }
        return blob
    } catch (error) {
        lemonToast.error('Failed to take screenshot: ' + error)
        return null
    }
}
