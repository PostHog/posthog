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
                    if (urlOrPath.includes('posthog.com')) {
                        if (urlOrPath.indexOf(POSTHOG_COM_DOMAIN) === 0) {
                            path = urlOrPath.substring(POSTHOG_COM_DOMAIN.length)
                        }
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
