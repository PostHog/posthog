import { toBlob } from 'html-to-image'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

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

export async function captureScreenshot(): Promise<Blob | null> {
    try {
        const blob = await toBlob(document.body, { includeStyleProperties: allPropertyNames, quality: 0.4 })
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
