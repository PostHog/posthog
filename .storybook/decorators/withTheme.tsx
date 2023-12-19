import type { Decorator } from '@storybook/react'

/** Global story decorator that is used by the theming control to
 * switch between themes.
 */
export const withTheme: Decorator = (Story, context) => {
    const theme = context.globals.theme

    // set the body class
    if (document.body.classList.contains('posthog-3000')) {
        document.body.classList.add('posthog-3000')
    }

    // set the theme
    document.body.setAttribute('theme', theme === 'dark' ? 'dark' : 'light')

    return <Story />
}
