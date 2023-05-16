import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconPlus, IconJournal } from 'lib/lemon-ui/icons'
import { notebooksListLogic } from './notebooksListLogic'
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
    const { notebooks, notebooksLoading, scratchpadNotebook } = useValues(notebooksListLogic)
    const { loadNotebooks } = useActions(notebooksListLogic)

    const onVisibilityChange = useCallback((visible: boolean): void => {
        if (visible && !notebooksLoading) {
            loadNotebooks()
        }
    }, [])

    const items: LemonMenuItems = [
        {
            items: [
                {
                    label: 'Scratchpad',
                    onClick: () => onSelectNotebook(scratchpadNotebook),
                },
            ],
        },
        {
            items: notebooks.length
                ? notebooks.map((notebook) => ({
                      label: notebook.title,
                      onClick: () => onSelectNotebook(notebook),
                  }))
                : [
                      {
                          label: 'No notebooks',
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
            <LemonButton size="small" icon={<IconJournal />} status="primary-alt">
                <span className="font-semibold">{selectedNotebookId || 'Notebooks'}</span>
            </LemonButton>
        </LemonMenu>
    )
}
