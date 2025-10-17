import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { notebooksModel } from '~/models/notebooksModel'

import { NotebookSelectPopover } from '../NotebookSelectButton/NotebookSelectButton'
import { NotebookListItemType } from '../types'

export type NotebookListMiniProps = {
    selectedNotebookId?: string
    onSelectNotebook: (notebook: NotebookListItemType) => void
}

export function NotebookListMini({ selectedNotebookId }: NotebookListMiniProps): JSX.Element {
    const { notebooks, notebookTemplates } = useValues(notebooksModel)

    const selectedTitle =
        selectedNotebookId === 'scratchpad'
            ? 'My scratchpad'
            : notebookTemplates.find((notebook) => notebook.short_id === selectedNotebookId)?.title ||
              notebooks.find((notebook) => notebook.short_id === selectedNotebookId)?.title ||
              'Untitled'

    return (
        <NotebookSelectPopover placement="bottom-start">
            <LemonButton size="small" truncate>
                {selectedTitle || 'Notebooks'}
            </LemonButton>
        </NotebookSelectPopover>
    )
}
