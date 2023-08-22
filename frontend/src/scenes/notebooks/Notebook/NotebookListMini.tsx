import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconPlus, IconJournal } from 'lib/lemon-ui/icons'
import { notebooksModel } from '~/models/notebooksModel'
import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { NotebookListItemType } from '~/types'
import { useCallback } from 'react'

export type NotebookListMiniProps = {
    selectedNotebookId?: string
    onSelectNotebook: (notebook: NotebookListItemType) => void
    onNewNotebook?: () => void
}

export function NotebookListMini({
    selectedNotebookId,
    onSelectNotebook,
    onNewNotebook,
}: NotebookListMiniProps): JSX.Element {
    const { notebooks, notebookTemplates, notebooksLoading, scratchpadNotebook } = useValues(notebooksModel)
    const { loadNotebooks } = useActions(notebooksModel)

    const onVisibilityChange = useCallback((visible: boolean): void => {
        if (visible && !notebooksLoading) {
            loadNotebooks()
        }
    }, [])

    const selectedTitle =
        selectedNotebookId === 'scratchpad'
            ? 'Scratchpad'
            : notebookTemplates.find((notebook) => notebook.short_id === selectedNotebookId)?.title ||
              notebooks.find((notebook) => notebook.short_id === selectedNotebookId)?.title ||
              'Untitled'

    const items: LemonMenuItems = [
        {
            items: [
                {
                    label: 'Scratchpad',
                    onClick: () => onSelectNotebook(scratchpadNotebook),
                    active: selectedNotebookId === 'scratchpad',
                },
            ],
        },
        {
            items: notebooks.length
                ? notebooks.map((notebook) => ({
                      label: notebook.title ?? `Untitled (${notebook.short_id})`,
                      onClick: () => onSelectNotebook(notebook),
                      active: notebook.short_id === selectedNotebookId,
                  }))
                : [
                      {
                          label: notebooksLoading ? 'Loading notebooks...' : 'No notebooks',
                          disabledReason: 'No notebooks found',
                          onClick: () => {},
                      },
                  ],
        },
    ]

    if (onNewNotebook) {
        items.push({
            items: [
                {
                    label: 'New notebook',
                    status: 'primary',
                    icon: <IconPlus />,
                    onClick: () => onNewNotebook(),
                },
            ],
        })
    }

    return (
        <LemonMenu placement="right-start" items={items} onVisibilityChange={onVisibilityChange}>
            <LemonButton size="small" icon={<IconJournal />} status="primary-alt" sideIcon={null}>
                <span className="font-semibold">{selectedTitle || 'Notebooks'}</span>
            </LemonButton>
        </LemonMenu>
    )
}
