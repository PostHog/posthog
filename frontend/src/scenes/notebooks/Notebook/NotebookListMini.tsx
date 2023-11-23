import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { notebooksModel } from '~/models/notebooksModel'
import { NotebookListItemType } from '~/types'

import { IconNotebook } from '../IconNotebook'
import { NotebookSelectPopover } from '../NotebookSelectButton/NotebookSelectButton'

export type NotebookListMiniProps = {
    selectedNotebookId?: string
    onSelectNotebook: (notebook: NotebookListItemType) => void
}

export function NotebookListMini({ selectedNotebookId }: NotebookListMiniProps): JSX.Element {
    const { notebooks, notebookTemplates } = useValues(notebooksModel)

    const is3000 = useFeatureFlag('POSTHOG_3000')

    const selectedTitle =
        selectedNotebookId === 'scratchpad'
            ? 'My scratchpad'
            : notebookTemplates.find((notebook) => notebook.short_id === selectedNotebookId)?.title ||
              notebooks.find((notebook) => notebook.short_id === selectedNotebookId)?.title ||
              'Untitled'

    return (
        <NotebookSelectPopover placement="bottom-start">
            <LemonButton size="small" icon={!is3000 ? <IconNotebook /> : null} status="primary-alt">
                <span className="font-semibold truncate">{selectedTitle || 'Notebooks'}</span>
            </LemonButton>
        </NotebookSelectPopover>
    )
}
