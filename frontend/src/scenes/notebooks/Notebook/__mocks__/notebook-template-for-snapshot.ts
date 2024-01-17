import { MOCK_DEFAULT_BASIC_USER } from 'lib/api.mock'
import { JSONContent } from 'scenes/notebooks/Notebook/utils'

import { NotebookType } from '~/types'

export const notebookTestTemplate = (
    title: string = 'Notebook for snapshots',
    notebookJson: JSONContent[]
): NotebookType => ({
    id: 'template-introduction',
    short_id: 'template-introduction',
    title: title,
    created_at: '2023-06-02T00:00:00Z',
    last_modified_at: '2023-06-02T00:00:00Z',
    created_by: MOCK_DEFAULT_BASIC_USER,
    last_modified_by: MOCK_DEFAULT_BASIC_USER,
    version: 1,
    content: {
        type: 'doc',
        content: [
            {
                type: 'heading',
                attrs: {
                    level: 1,
                },
                content: [
                    {
                        type: 'text',
                        text: title,
                    },
                ],
            },
            ...notebookJson,
        ],
    },
})
