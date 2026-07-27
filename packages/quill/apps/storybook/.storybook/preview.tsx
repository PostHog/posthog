import './storybook.css'

import { DocsContainer } from '@storybook/addon-docs/blocks'
import type { Preview } from '@storybook/react'
import { themes } from 'storybook/theming'
import React, { useEffect, useState } from 'react'
import { useDarkMode } from 'storybook-dark-mode'

// The Docs container renders outside Storybook's preview-hooks context, so
// `useDarkMode()` (a preview hook) can't be used here. Track the `<html>.dark`
// class the story decorator sets via a MutationObserver instead.
function ThemedDocsContainer(props: React.ComponentProps<typeof DocsContainer>): React.ReactElement {
    const [isDark, setIsDark] = useState<boolean>(() => document.documentElement.classList.contains('dark'))

    useEffect(() => {
        const root = document.documentElement
        const observer = new MutationObserver(() => setIsDark(root.classList.contains('dark')))
        observer.observe(root, { attributes: true, attributeFilter: ['class'] })
        return () => observer.disconnect()
    }, [])

    return <DocsContainer {...props} theme={isDark ? themes.dark : themes.light} />
}

const preview: Preview = {
    globalTypes: {
        desktop: {
            name: 'Desktop mode',
            description: 'Toggle the Electron desktop app surface (adds `is-desktop` to <body>)',
            defaultValue: 'web',
            toolbar: {
                icon: 'browser',
                items: [
                    { value: 'web', icon: 'browser', title: 'Web (pointer cursor)' },
                    { value: 'desktop', icon: 'box', title: 'Desktop (default cursor)' },
                ],
                dynamicTitle: true,
            },
        },
    },
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
        options: {
            // Deterministic sidebar: without this, order is file-discovery
            // order, and the dev server appends newly created story files to
            // the end of the live index until a restart.
            storySort: {
                order: ['Tokens', 'Examples', 'Primitives', 'Components'],
                method: 'alphabetical',
            },
        },
    },
    decorators: [
        // Mirrors the `desktop` toolbar global onto `<body class="is-desktop">`,
        // matching how the Electron app tags its shell — lets the cursor reset
        // (and any future desktop-only styling) be previewed live.
        (Story, context) => {
            const isDesktop = context.globals.desktop === 'desktop'

            useEffect(() => {
                document.body.classList.toggle('is-desktop', isDesktop)
                return () => document.body.classList.remove('is-desktop')
            }, [isDesktop])

            return <Story />
        },
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
