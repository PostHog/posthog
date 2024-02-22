import { useValues } from 'kea'
import { useEffect } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

export function useThemedBody(): void {
    const { isDarkModeOn } = useValues(themeLogic)

    useEffect(() => {
        document.body.setAttribute('theme', isDarkModeOn ? 'dark' : 'light')
        // overflow-hidden since each area handles scrolling individually (e.g. navbar, scene, side panel)
        document.body.classList.add('overflow-hidden')
    }, [isDarkModeOn])
}
