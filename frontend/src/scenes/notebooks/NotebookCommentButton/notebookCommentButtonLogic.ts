import { events, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import { NotebookListItemType, NotebookNodeType } from '~/types'

import api from 'lib/api'

import type { notebookCommentButtonLogicType } from './notebookCommentButtonLogicType'

export interface NotebookCommentButtonProps {
    sessionRecordingId: string
}

export const notebookCommentButtonLogic = kea<notebookCommentButtonLogicType>([
    path((key) => ['scenes', 'session-recordings', 'NotebookCommentButton', 'multiNotebookCommentButtonLogic', key]),
    props({} as NotebookCommentButtonProps),
    key((props) => props.sessionRecordingId || 'no recording id yet'),
    loaders(({ props }) => ({
        notebooks: [
            [] as NotebookListItemType[],
            {
                loadNotebooks: async () => {
                    const response = await api.notebooks.list([
                        { type: NotebookNodeType.Recording, attrs: { id: props.sessionRecordingId } },
                    ])
                    // TODO for simplicity we'll assume the results will fit into one page
                    return response.results
                },
            },
        ],
    })),
    events(({ actions }) => ({
        afterMount: actions.loadNotebooks,
    })),
])
