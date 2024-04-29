import { actions, kea, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { RefObject } from 'react'

import { HogQLQuery, NodeKind } from '~/queries/schema'
import { hogql } from '~/queries/utils'
import { PostHogAppToolbarEvent } from '~/toolbar/bar/toolbarLogic'

import type { heatmapsBrowserLogicType } from './heatmapsBrowserLogicType'

export type HeatmapsBrowserLogicProps = {
    iframeRef: RefObject<HTMLIFrameElement | null>
}

export const heatmapsBrowserLogic = kea<heatmapsBrowserLogicType>([
    path(['scenes', 'heatmaps', 'heatmapsBrowserLogic']),
    props({} as HeatmapsBrowserLogicProps),

    actions({
        setBrowserSearch: (searchTerm: string) => ({ searchTerm }),
        setBrowserUrl: (url: string) => ({ url }),
        setIframePosthogJsConnected: (ready: boolean) => ({ ready }),
        onIframeLoad: true,
        sendToolbarMessage: (type: PostHogAppToolbarEvent, payload?: Record<string, any>) => ({
            type,
            payload,
        }),
    }),

    loaders({
        browserSearchOptions: [
            null as string[] | null,
            {
                setBrowserSearch: async ({ searchTerm }) => {
                    const query: HogQLQuery = {
                        kind: NodeKind.HogQLQuery,
                        query: hogql`SELECT distinct properties.$current_url AS urls
                                FROM events
                                WHERE timestamp >= now() - INTERVAL 7 DAY
                                AND timestamp <= now()
                                AND properties.$current_url like '%${hogql.identifier(searchTerm)}%'
                                ORDER BY timestamp DESC
                                limit 100`,
                    }

                    const res = await api.query(query)

                    return res.results?.map((x) => x[0]) as string[]
                },
            },
        ],
    }),

    reducers({
        browserUrl: [
            null as string | null,
            { persist: true },
            {
                setBrowserUrl: (_, { url }) => url,
            },
        ],
        iframePosthogJsConnected: [
            false as boolean,
            {
                setIframePosthogJsConnected: (_, { ready }) => ready,
            },
        ],
    }),

    listeners(({ actions, props }) => ({
        sendToolbarMessage: ({ type, payload }) => {
            props.iframeRef?.current?.contentWindow?.postMessage(
                {
                    type,
                    payload,
                },
                '*'
            )
        },

        onIframeLoad: () => {
            // NOTE: We setup event listeners and messages here that are picked up by `toolbarLogic.ts`
            // NOTE: It could happen that the toolbar isn't ready - we might want to have a 2 way sync...
            actions.sendToolbarMessage(PostHogAppToolbarEvent.PH_APP_CONTEXT)
            actions.sendToolbarMessage(PostHogAppToolbarEvent.PH_HEATMAPS_CONFIG, {
                enabled: true,
            })
        },
    })),
])
