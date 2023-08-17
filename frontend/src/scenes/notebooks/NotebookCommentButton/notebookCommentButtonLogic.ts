import { actions, events, kea, key, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { NotebookListItemType, NotebookNodeType } from '~/types'

import api from 'lib/api'

import type { notebookCommentButtonLogicType } from './notebookCommentButtonLogicType'

export interface NotebookCommentButtonProps {
    sessionRecordingId: string
    startVisible: boolean
}

export const notebookCommentButtonLogic = kea<notebookCommentButtonLogicType>([
    path((key) => ['scenes', 'session-recordings', 'NotebookCommentButton', 'multiNotebookCommentButtonLogic', key]),
    props({} as NotebookCommentButtonProps),
    key((props) => props.sessionRecordingId || 'no recording id yet'),
    actions({
        setShowPopover: (visible: boolean) => ({ visible }),
    }),
    reducers(({ props }) => ({
        showPopover: [
            props.startVisible,
            {
                setShowPopover: (_, { visible }) => visible,
            },
        ],
    })),
    loaders(({ props }) => ({
        notebooks: [
            [] as NotebookListItemType[],
            {
                loadContainingNotebooks: async () => {
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
        afterMount: () => {
            actions.loadContainingNotebooks()
        },
    })),
])
