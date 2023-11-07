import { actions, kea, reducers, path, listeners, connect } from 'kea'
import { SidePanelTab, sidePanelLogic } from '../sidePanelLogic'

import type { sidePanelDocsLogicType } from './sidePanelDocsLogicType'

const POSTHOG_COM_DOMAIN = 'https://posthog.com'

export const sidePanelDocsLogic = kea<sidePanelDocsLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelDocsLogic']),
    connect({
        actions: [sidePanelLogic, ['openSidePanel', 'closeSidePanel']],
    }),

    actions({
        openDocsPage: (urlOrPath: string) => ({ urlOrPath }),
    }),

    reducers(() => ({
        path: [
            '/docs' as string,
            {
                openDocsPage: (_, { urlOrPath }) => {
                    let path = urlOrPath
                    try {
                        const url = new URL(urlOrPath)
                        if (url.origin === POSTHOG_COM_DOMAIN) {
                            path = url.pathname + url.search
                        }
                    } catch (e) {
                        // not a valid URL, continue
                    }

                    return path[0] === '/' ? path : `/${path}`
                },
            },
        ],
    })),

    listeners(({ actions }) => ({
        openDocsPage: () => {
            actions.openSidePanel(SidePanelTab.Docs)
        },
    })),
])
