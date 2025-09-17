import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { sceneLogic } from 'scenes/sceneLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

export function useThemedHtml(overflowHidden = true): void {
    const { isDarkModeOn, customCss } = useValues(themeLogic)
    const { sceneConfig } = useValues(sceneLogic)

    const CUSTOM_THEME_STYLES_ID = 'ph-custom-theme-styles'

    useEffect(() => {
        const oldStyle = document.getElementById(CUSTOM_THEME_STYLES_ID)
        if (oldStyle) {
            document.head.removeChild(oldStyle)
        }

        document.body.setAttribute('theme', isDarkModeOn ? 'dark' : 'light')

        if (customCss) {
            const newStyle = document.createElement('style')
            newStyle.id = CUSTOM_THEME_STYLES_ID
            newStyle.appendChild(document.createTextNode(customCss))
            document.head.appendChild(newStyle)
        }
    }, [isDarkModeOn, customCss])

    useEffect(() => {
        // overflow-hidden since each area handles scrolling individually (e.g. navbar, scene, side panel)
        if (overflowHidden) {
            document.body.classList.add('overflow-hidden')
        }
    }, [overflowHidden])

    useEffect(() => {
        // Add a theme-color meta tag to the head to change the address bar color on browsers that support it
        try {
            const root = document.documentElement
            const style = getComputedStyle(root)
            const backgroundColor = sceneConfig?.projectBased
                ? style.getPropertyValue('--surface-secondary')
                : style.getPropertyValue('--color-bg-bridge')

            document.head.querySelector('meta[name="theme-color"]')?.remove()
            document.head.insertAdjacentHTML('beforeend', `<meta name="theme-color" content="${backgroundColor}">`)
        } catch (e) {
            console.warn('Failed to set theme-color meta tag. This could indicate the variables no longer exist', e)
            posthog.captureException(new Error('Failed to set theme-color meta tag'), { extra: { error: e } })
        }
    }, [isDarkModeOn, sceneConfig?.projectBased])
}
