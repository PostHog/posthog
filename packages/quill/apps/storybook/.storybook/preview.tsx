import './storybook.css'

import React, { useEffect } from 'react'
import type { Preview } from 'storybook'

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
    initialGlobals: {
        theme: 'light',
    },
    decorators: [
        (Story, context) => {
            const theme = context.globals.theme || 'light'
            const isDark = theme === 'dark'

            useEffect(() => {
                document.documentElement.classList.toggle('dark', isDark)
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
