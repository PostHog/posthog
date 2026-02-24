import { useValues } from 'kea'

import { ButtonPrimitive, ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'
import { MenuOpenIndicator } from 'lib/ui/Menus/Menus'

import { notebooksModel } from '~/models/notebooksModel'

import { NotebookSelectPopover } from '../NotebookSelectButton/NotebookSelectButton'
import { NotebookListItemType } from '../types'

export type NotebookListMiniProps = {
    selectedNotebookId?: string
    onSelectNotebook: (notebook: NotebookListItemType) => void
    buttonProps?: ButtonPrimitiveProps
}

export function NotebookListMini({ selectedNotebookId, buttonProps }: NotebookListMiniProps): JSX.Element {
    const { notebooks, notebookTemplates } = useValues(notebooksModel)

    const selectedTitle =
        selectedNotebookId === 'scratchpad'
            ? 'My scratchpad'
            : notebookTemplates.find((notebook) => notebook.short_id === selectedNotebookId)?.title ||
              notebooks.find((notebook) => notebook.short_id === selectedNotebookId)?.title ||
              'Untitled'

    return (
        <NotebookSelectPopover placement="bottom-start">
            {(open) => (
                <ButtonPrimitive data-state={open ? 'open' : 'closed'} {...buttonProps}>
                    <span className="truncate">{selectedTitle || 'Notebooks'}</span>
                    <MenuOpenIndicator />
                </ButtonPrimitive>
            )}
        </NotebookSelectPopover>
    )
}
