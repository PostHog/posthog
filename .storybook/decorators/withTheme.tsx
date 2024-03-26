import type { Decorator } from '@storybook/react'

/** Global story decorator that is used by the theming control to
 * switch between themes.
 */
export const withTheme: Decorator = (Story, context) => {
    const theme = context.globals.theme

    document.body.setAttribute('theme', theme === 'dark' ? 'dark' : 'light') // For component stories
    document.cookie = `theme=${theme}; Path=/` // For scene stories, specifically `userLogic.selectors.themeMode`

    return <Story />
}
