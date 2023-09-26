import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { IconJournal } from 'lib/lemon-ui/icons'
import { notebooksModel } from '~/models/notebooksModel'
import { NotebookListItemType } from '~/types'
import { NotebookSelectPopover } from '../NotebookSelectButton/NotebookSelectButton'

export type NotebookListMiniProps = {
    selectedNotebookId?: string
    onSelectNotebook: (notebook: NotebookListItemType) => void
    onNewNotebook?: () => void
}

export function NotebookListMini({ selectedNotebookId }: NotebookListMiniProps): JSX.Element {
    const { notebooks, notebookTemplates } = useValues(notebooksModel)

    const selectedTitle =
        selectedNotebookId === 'scratchpad'
            ? 'Scratchpad'
            : notebookTemplates.find((notebook) => notebook.short_id === selectedNotebookId)?.title ||
              notebooks.find((notebook) => notebook.short_id === selectedNotebookId)?.title ||
              'Untitled'

    return (
        <NotebookSelectPopover placement="right-start">
            <LemonButton size="small" icon={<IconJournal />} status="primary-alt" sideIcon={null}>
                <span className="font-semibold">{selectedTitle || 'Notebooks'}</span>
            </LemonButton>
        </NotebookSelectPopover>
    )
}
