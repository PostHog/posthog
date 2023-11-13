import { actions, kea, reducers, path, listeners, connect, selectors } from 'kea'

import type { sidePanelDocsLogicType } from './sidePanelDocsLogicType'
import { sidePanelStateLogic } from '../sidePanelStateLogic'
import { SidePanelTab } from '~/types'

export const POSTHOG_WEBSITE_ORIGIN = 'https://posthog.com'

const sanitizePath = (path: string): string => {
    return path[0] === '/' ? path : `/${path}`
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
            let path = urlOrPath
            try {
                const url = new URL(urlOrPath)
                if (url.origin === POSTHOG_WEBSITE_ORIGIN) {
                    path = url.pathname + url.search
                }
            } catch (e) {
                // not a valid URL, continue
            }

            actions.setInitialPath(path)
            actions.openSidePanel(SidePanelTab.Docs)
        },

        unmountIframe: () => {
            // Update the initialPath so that next time we load it is the same as last time
            actions.setInitialPath(values.currentPath ?? '/docs')

            // TODO: Do we need to call this before the window unloads?
        },
    })),
])
