import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { SidePanelTab } from '~/types'

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
    }),

    actions({
        openDocsPage: (urlOrPath: string) => ({ urlOrPath }),
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
        openDocsPage: ({ urlOrPath }) => {
            actions.setInitialPath(getPathFromUrl(urlOrPath))
            actions.openSidePanel(SidePanelTab.Docs)
        },

        unmountIframe: () => {
            // Update the initialPath so that next time we load it is the same as last time
            actions.setInitialPath(values.currentPath ?? '/docs')
        },

        handleExternalUrl: ({ urlOrPath }) => {
            router.actions.push(getPathFromUrl(urlOrPath))
        },
    })),
])
