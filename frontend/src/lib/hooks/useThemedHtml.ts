import { captureException } from '@sentry/react'
import { useValues } from 'kea'
import { useEffect, useMemo } from 'react'
import { sceneLogic } from 'scenes/sceneLogic'

import { themeLogic, THEMES } from '~/layout/navigation-3000/themeLogic'

export function useThemedHtml(overflowHidden = true): void {
    const { isDarkModeOn, customThemeId } = useValues(themeLogic)
    const { sceneConfig } = useValues(sceneLogic)

    const CUSTOM_THEME_STYLES_ID = 'ph-custom-theme-styles'

    const customCss = useMemo(() => {
        if (!customThemeId) {
            return
        }

        const customTheme = THEMES[customThemeId]
        if (!customTheme) {
            return
        }

        return customTheme.styles
    }, [customThemeId])

    useEffect(() => {
        const oldStyle = document.getElementById(CUSTOM_THEME_STYLES_ID)
        if (oldStyle) {
            document.head.removeChild(oldStyle)
        }

        if (!customCss) {
            document.body.setAttribute('theme', isDarkModeOn ? 'dark' : 'light')
            return
        }

        document.body.removeAttribute('theme')

        const newStyle = document.createElement('style')
        newStyle.id = CUSTOM_THEME_STYLES_ID
        newStyle.appendChild(document.createTextNode(customCss))
        document.head.appendChild(newStyle)
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
                ? style.getPropertyValue(isDarkModeOn ? '--accent-3000-dark' : '--accent-3000-light')
                : style.getPropertyValue('--bg-bridge')

            document.head.querySelector('meta[name="theme-color"]')?.remove()
            document.head.insertAdjacentHTML('beforeend', `<meta name="theme-color" content="${backgroundColor}">`)
        } catch (e) {
            console.warn('Failed to set theme-color meta tag. This could indicate the variables no longer exist', e)
            captureException(new Error('Failed to set theme-color meta tag'), { extra: { error: e } })
        }
    }, [isDarkModeOn, sceneConfig?.projectBased])
}
