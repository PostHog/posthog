import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import { RefObject } from 'react'
import { sceneLogic } from 'scenes/sceneLogic'

import { sidePanelStateLogic } from '../sidePanelStateLogic'
import type { sidePanelDocsLogicType } from './sidePanelDocsLogicType'

export const POSTHOG_WEBSITE_ORIGIN = 'https://posthog.com'

const sanitizePath = (path: string): string => {
    return path[0] === '/' ? path : `/${path}`
}

export const getPathFromUrl = (urlOrPath: string): string => {
    // NOTE: This is not a perfect function - it is mostly meant for the specific use cases of these docs
    try {
        const url = new URL(urlOrPath)
        return url.pathname + url.search + url.hash
    } catch {
        return urlOrPath
    }
}

export type DocsMenuOption = {
    name: string
    url: string
}

export type SidePanelDocsLogicProps = {
    iframeRef: RefObject<HTMLIFrameElement | null>
}

export const sidePanelDocsLogic = kea<sidePanelDocsLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelDocsLogic']),
    props({} as SidePanelDocsLogicProps),
    connect(() => ({
        actions: [sidePanelStateLogic, ['openSidePanel', 'closeSidePanel', 'setSidePanelOptions']],
        values: [sceneLogic, ['sceneConfig'], sidePanelStateLogic, ['selectedTabOptions']],
    })),

    actions({
        updatePath: (path: string) => ({ path }),
        setInitialPath: (path: string) => ({ path }),
        unmountIframe: true,
        handleExternalUrl: (urlOrPath: string) => ({ urlOrPath }),
        setMenuOptions: (menuOptions: DocsMenuOption[] | null) => ({ menuOptions }),
        setIframeReady: (ready: boolean) => ({ ready }),
        setActiveMenuName: (activeMenuName: string | null) => ({ activeMenuName }),
        navigateToPage: (path: string) => ({ path }),
    }),

    reducers(() => ({
        iframeReady: [
            false as boolean,
            {
                setIframeReady: (_, { ready }) => ready,
            },
        ],
        menuOptions: [
            null as DocsMenuOption[] | null,
            {
                setMenuOptions: (_, { menuOptions }) => menuOptions,
            },
        ],
        activeMenuName: [
            null as string | null,
            {
                setActiveMenuName: (_, { activeMenuName }) => activeMenuName,
            },
        ],
        currentPath: [
            null as string | null,
            {
                updatePath: (_, { path }) => sanitizePath(path),
            },
        ],
        initialPath: [
            '/docs' as string,
            { persist: true },
            {
                setInitialPath: (_, { path }) => sanitizePath(path),
            },
        ],
    })),

    selectors({
        iframeSrc: [
            (s) => [s.initialPath],
            (initialPath) => {
                return `${POSTHOG_WEBSITE_ORIGIN}${initialPath ?? ''}`
            },
        ],
        currentUrl: [
            (s) => [s.currentPath],
            (currentPath) => {
                return `${POSTHOG_WEBSITE_ORIGIN}${currentPath ?? ''}`
            },
        ],
    }),

    listeners(({ actions, values, props }) => ({
        openSidePanel: ({ options }) => {
            if (options) {
                const initialPath = getPathFromUrl(options)
                actions.setInitialPath(initialPath)
                actions.navigateToPage(initialPath)
            }
        },

        unmountIframe: () => {
            // Update the initialPath so that next time we load it is the same as last time
            actions.setInitialPath(values.currentPath ?? '/docs')
        },

        handleExternalUrl: ({ urlOrPath }) => {
            router.actions.push(getPathFromUrl(urlOrPath))
        },

        navigateToPage: ({ path }) => {
            if (path) {
                props.iframeRef.current?.contentWindow?.postMessage(
                    {
                        type: 'navigate',
                        url: path,
                    },
                    '*'
                )
            }
        },

        updatePath: ({ path }) => {
            actions.setSidePanelOptions(path)
        },
    })),

    afterMount(({ actions, values, cache }) => {
        // If a destination was set in the options, use that
        // otherwise the default for the current scene
        // otherwise, whatever it last was set to
        if (values.selectedTabOptions) {
            const initialPath = getPathFromUrl(values.selectedTabOptions)
            actions.setInitialPath(initialPath)
        } else if (values.sceneConfig?.defaultDocsPath) {
            actions.setInitialPath(values.sceneConfig?.defaultDocsPath)
        }

        cache.onWindowMessage = (event: MessageEvent): void => {
            if (event.origin === POSTHOG_WEBSITE_ORIGIN) {
                if (event.data.type === 'internal-navigation') {
                    actions.updatePath(event.data.url)
                    return
                }
                if (event.data.type === 'docs-ready') {
                    actions.setIframeReady(true)
                    return
                }

                if (event.data.type === 'external-navigation') {
                    // This should only be triggered for us|eu.posthog.com links
                    actions.handleExternalUrl(event.data.url)
                    return
                }
                if (event.data.type === 'docs-menu') {
                    actions.setMenuOptions(event.data.menu)
                    return
                }

                if (event.data.type === 'docs-active-menu') {
                    actions.setActiveMenuName(event.data.activeMenuName)
                    return
                }

                console.warn('Unhandled iframe message from Docs:', event.data)
            }
        }

        window.addEventListener('message', cache.onWindowMessage)
    }),

    beforeUnmount(({ actions, values, cache }) => {
        actions.setInitialPath(values.currentPath ?? '/docs')

        window.removeEventListener('message', cache.onWindowMessage)
    }),
])
