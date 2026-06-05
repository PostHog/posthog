import './storybook.css'

import React, { useEffect } from 'react'
import type { Preview } from '@storybook/react'
import { themes } from '@storybook/theming'
import { DocsContainer } from '@storybook/addon-docs'
import { useDarkMode } from 'storybook-dark-mode'

function ThemedDocsContainer(props: React.ComponentProps<typeof DocsContainer>): React.ReactElement {
    const isDark = useDarkMode()
    return <DocsContainer {...props} theme={isDark ? themes.dark : themes.light} />
}

const preview: Preview = {
    parameters: {
        controls: {
            matchers: {
                color: /(background|color)$/i,
                date: /Date$/i,
            },
        },
        // storybook-dark-mode: drives the toolbar toggle + autodocs container.
        // `appBg` paints the inline story canvas behind the decorator wrapper
        // so the entire iframe matches the active theme without per-element
        // !important hacks.
        darkMode: {
            stylePreview: true,
            light: {
                ...themes.light,
                appBg: '#ffffff',
            },
            dark: {
                ...themes.dark,
                appBg: '#0a0a0a',
            },
        },
        docs: {
            container: ThemedDocsContainer,
        },
    },
    decorators: [
        // Hooks must run at the decorator's top level — Storybook's preview
        // hooks context (which `useDarkMode` relies on) is only active here,
        // not inside nested components a decorator renders. Syncs the signal to
        // `<html>` class/attribute so quill's `--background` etc. resolve to dark.
        (Story) => {
            const isDark = useDarkMode()

            useEffect(() => {
                document.documentElement.classList.toggle('dark', isDark)
                if (isDark) {
                    document.documentElement.setAttribute('theme', 'dark')
                } else {
                    document.documentElement.removeAttribute('theme')
                }
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
