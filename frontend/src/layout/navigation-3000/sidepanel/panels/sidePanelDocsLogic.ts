import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'
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
    } catch (e) {
        return urlOrPath
    }
}

export const sidePanelDocsLogic = kea<sidePanelDocsLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelDocsLogic']),
    connect({
        actions: [sidePanelStateLogic, ['openSidePanel', 'closeSidePanel']],
        values: [sceneLogic, ['sceneConfig'], sidePanelStateLogic, ['selectedTabOptions']],
    }),

    actions({
        updatePath: (path: string) => ({ path }),
        setInitialPath: (path: string) => ({ path }),
        unmountIframe: true,
        handleExternalUrl: (urlOrPath: string) => ({ urlOrPath }),
    }),

    reducers(() => ({
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

    listeners(({ actions, values }) => ({
        openSidePanel: ({ options }) => {
            if (options) {
                const initialPath = getPathFromUrl(options)
                actions.setInitialPath(initialPath)
            }
        },

        unmountIframe: () => {
            // Update the initialPath so that next time we load it is the same as last time
            actions.setInitialPath(values.currentPath ?? '/docs')
        },

        handleExternalUrl: ({ urlOrPath }) => {
            router.actions.push(getPathFromUrl(urlOrPath))
        },
    })),

    afterMount(({ actions, values }) => {
        // If a destination was set in the options, use that
        // otherwise the default for the current scene
        // otherwise, whatever it last was set to
        if (values.selectedTabOptions) {
            const initialPath = getPathFromUrl(values.selectedTabOptions)
            actions.setInitialPath(initialPath)
        } else if (values.sceneConfig?.defaultDocsPath) {
            actions.setInitialPath(values.sceneConfig?.defaultDocsPath)
        }
    }),

    beforeUnmount(({ actions, values }) => {
        actions.setInitialPath(values.currentPath ?? '/docs')
    }),
])
