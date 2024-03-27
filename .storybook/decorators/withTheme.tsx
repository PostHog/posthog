import type { Decorator } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'
import { userLogic } from 'scenes/userLogic'

/** Global story decorator that is used by the theming control to
 * switch between themes.
 */
export const withTheme: Decorator = (Story, context) => {
    const theme = context.globals.theme

    const { __testOnlyOverrideThemeFromCookie } = useActions(userLogic)

    useEffect(() => {
        document.body.setAttribute('theme', theme)
        __testOnlyOverrideThemeFromCookie(theme)
    }, [theme])

    return <Story />
}
