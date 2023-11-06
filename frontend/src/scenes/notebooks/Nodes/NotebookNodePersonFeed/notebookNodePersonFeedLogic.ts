import { kea, key, path, props, afterMount } from 'kea'
import { loaders } from 'kea-loaders'

import { query } from '~/queries/query'
import { NodeKind, SessionsTimelineQuery, SessionsTimelineQueryResponse } from '~/queries/schema'

import type { notebookNodePersonFeedLogicType } from './notebookNodePersonFeedLogicType'

export type NotebookNodePersonFeedLogicProps = {
    personId: string
}

export const notebookNodePersonFeedLogic = kea<notebookNodePersonFeedLogicType>([
    props({} as NotebookNodePersonFeedLogicProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'Nodes', 'notebookNodePersonFeedLogic', key]),
    key(({ personId }) => personId),

    loaders(({ props }) => ({
        sessions: [
            null as SessionsTimelineQueryResponse['results'] | null,
            {
                loadSessionsTimeline: async () => {
                    const result = await query<SessionsTimelineQuery>({
                        kind: NodeKind.SessionsTimelineQuery,
                        personId: props.personId,
                    })
                    return result.results
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadSessionsTimeline()
    }),
])
