import type { Decorator } from '@storybook/react'

/** Global story decorator that is used by the theming control to
 * switch between themes.
 */
export const withTheme: Decorator = (Story, context) => {
    const theme = context.globals.theme

    // set the body class. unfortunately this doesn't work on the initial render,
    // meaning we need to toggle the theme one time for it to work. won't fix
    // this, since we're removing the body class soon enough.
    if (!document.body.classList.contains('posthog-3000')) {
        document.body.classList.add('posthog-3000')
    }

    // set the theme
    document.body.setAttribute('theme', theme === 'dark' ? 'dark' : 'light')

    return <Story />
}
