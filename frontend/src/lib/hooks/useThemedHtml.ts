import { captureException } from '@sentry/react'
import { useValues } from 'kea'
import { useEffect } from 'react'
import { sceneLogic } from 'scenes/sceneLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

export function useThemedHtml(): void {
    const { isDarkModeOn } = useValues(themeLogic)
    const { sceneConfig } = useValues(sceneLogic)

    useEffect(() => {
        document.body.setAttribute('theme', isDarkModeOn ? 'dark' : 'light')
        // overflow-hidden since each area handles scrolling individually (e.g. navbar, scene, side panel)
        document.body.classList.add('overflow-hidden')
    }, [isDarkModeOn])

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
