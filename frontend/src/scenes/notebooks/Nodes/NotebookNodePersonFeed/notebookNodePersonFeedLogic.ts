import { kea, key, path, props, afterMount } from 'kea'
import { loaders } from 'kea-loaders'

// import { query } from '~/queries/query'
// import {
//     // NodeKind,
//     // SessionsTimelineQuery,
//     SessionsTimelineQueryResponse,
// } from '~/queries/schema'

import mockSessionsTimelineQueryResponse from './mockSessionsTimelineQueryResponse.json'

import type { notebookNodePersonFeedLogicType } from './notebookNodePersonFeedLogicType'

export type NotebookNodePersonFeedLogicProps = {
    personId: string
}

export const notebookNodePersonFeedLogic = kea<notebookNodePersonFeedLogicType>([
    props({} as NotebookNodePersonFeedLogicProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'Nodes', 'notebookNodePersonFeedLogic', key]),
    key(({ personId }) => personId),

    loaders(() => ({
        sessions: [
            // null as SessionsTimelineQueryResponse['results'] | null,
            null as any | null,
            {
                loadSessionsTimeline: async () => {
                    // const result = await query<SessionsTimelineQuery>({
                    //     kind: NodeKind.SessionsTimelineQuery,
                    //     after: '2021-01-01T18:00:00Z',
                    //     before: '2024-01-01T06:00:00Z',
                    //     personId: props.personId,
                    // })
                    const result = mockSessionsTimelineQueryResponse
                    return result.results
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadSessionsTimeline()
    }),
])
