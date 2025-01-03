import type { Decorator } from '@storybook/react'

/** Global story decorator that is used by the theming control to
 * switch between themes.
 */
export const withTheme: Decorator = (Story, context) => {
    const theme = context.globals.theme

    // set the theme
    document.body.setAttribute('theme', theme === 'dark' ? 'dark' : 'light')

    document.body.classList.remove('theme-light', 'theme-dark')
    document.body.classList.add(theme === 'dark' ? 'theme-dark' : 'theme-light')

    return <Story />
}
