import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { getEmbedContext } from 'lib/embed/embedContext'
import { themeLogic } from 'lib/logic/themeLogic'
import { sceneLogic } from 'scenes/sceneLogic'

export function useThemedHtml(overflowHidden = true, forcedTheme: 'light' | 'dark' | null = null): void {
    const { isDarkModeOn, customCss } = useValues(themeLogic)
    const { sceneConfig } = useValues(sceneLogic)
    const isDarkTheme = forcedTheme ? forcedTheme === 'dark' : isDarkModeOn

    const CUSTOM_THEME_STYLES_ID = 'ph-custom-theme-styles'
    // Embedded in another shell, the app owns only its root element: the host page keeps its own
    // body classes, theme, custom styles and theme-color meta tag.
    const embedContext = getEmbedContext()

    useEffect(() => {
        const oldStyle = document.getElementById(CUSTOM_THEME_STYLES_ID)
        if (oldStyle) {
            document.head.removeChild(oldStyle)
        }

        const themeTarget = embedContext?.root ?? document.body
        themeTarget.setAttribute('theme', isDarkTheme ? 'dark' : 'light')

        if (customCss && !embedContext) {
            const newStyle = document.createElement('style')
            newStyle.id = CUSTOM_THEME_STYLES_ID
            newStyle.appendChild(document.createTextNode(customCss))
            document.head.appendChild(newStyle)
        }
    }, [customCss, isDarkTheme, embedContext])

    useEffect(() => {
        // overflow-hidden since each area handles scrolling individually (e.g. navbar, scene, side panel)
        if (overflowHidden && !embedContext) {
            document.body.classList.add('overflow-hidden')
        }
    }, [overflowHidden, embedContext])

    useEffect(() => {
        if (embedContext) {
            return
        }
        // Add a theme-color meta tag to the head to change the address bar color on browsers that support it
        try {
            const root = document.documentElement
            const style = getComputedStyle(root)
            const backgroundColor = sceneConfig?.projectBased
                ? style.getPropertyValue('--surface-secondary')
                : style.getPropertyValue('--color-bg-bridge')

            document.head.querySelector('meta[name="theme-color"]')?.remove()
            const meta = document.createElement('meta')
            meta.name = 'theme-color'
            meta.content = backgroundColor
            document.head.appendChild(meta)
        } catch (e) {
            console.warn('Failed to set theme-color meta tag. This could indicate the variables no longer exist', e)
            posthog.captureException(new Error('Failed to set theme-color meta tag'), { extra: { error: e } })
        }
    }, [isDarkTheme, sceneConfig?.projectBased, embedContext])
}
