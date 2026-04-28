import './storybook.css'

import React, { useEffect } from 'react'
import type { Preview } from '@storybook/react'

const preview: Preview = {
    parameters: {
        controls: {
            matchers: {
                color: /(background|color)$/i,
                date: /Date$/i,
            },
        },
    },
    globalTypes: {
        theme: {
            description: 'Toggle light/dark theme',
            defaultValue: 'light',
            toolbar: {
                title: 'Theme',
                icon: 'paintbrush',
                items: [
                    { value: 'light', title: 'Light', icon: 'sun' },
                    { value: 'dark', title: 'Dark', icon: 'moon' },
                ],
                dynamicTitle: true,
            },
        },
    },
    decorators: [
        (Story, context) => {
            const theme = context.globals.theme || 'light'
            const isDark = theme === 'dark'

            useEffect(() => {
                // Set both .dark class and theme="dark" attribute so the
                // toolbar toggle validates both dark mode selectors at once.
                document.documentElement.classList.toggle('dark', isDark)
                if (isDark) {
                    document.documentElement.setAttribute('theme', 'dark')
                } else {
                    document.documentElement.removeAttribute('theme')
                }
                document.body.style.backgroundColor = ''
            }, [isDark])

            return (
                <div className="bg-background text-foreground" style={{ padding: '1rem' }}>
                    <Story />
                </div>
            )
        },
    ],
}

export default preview
