import { useValues } from 'kea'
import { useEffect } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

export function use3000Body(): void {
    const { isDarkModeOn } = useValues(themeLogic)

    useEffect(() => {
        document.body.setAttribute('theme', isDarkModeOn ? 'dark' : 'light')
        document.body.classList.add('posthog-3000')
    }, [isDarkModeOn])
}
