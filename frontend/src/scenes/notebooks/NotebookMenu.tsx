import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconClock, IconCopy, IconDownload, IconEllipsis, IconShare, IconTrash } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { urls } from 'scenes/urls'

import { notebooksModel } from '~/models/notebooksModel'

import { NotebookLogicProps, notebookLogic } from './Notebook/notebookLogic'

export function NotebookMenu({ shortId }: NotebookLogicProps): JSX.Element {
    const { notebook, showHistory, isLocalOnly } = useValues(notebookLogic({ shortId }))
    const { openShareModal, duplicateNotebook, exportJSON, setShowHistory } = useActions(notebookLogic({ shortId }))

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive iconOnly>
                    <IconEllipsis className="text-tertiary size-3 group-hover:text-primary z-10" />
                </ButtonPrimitive>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="center" side="bottom">
                <DropdownMenuGroup>
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive onClick={() => duplicateNotebook()} menuItem>
                            <IconCopy />
                            Duplicate
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive onClick={() => exportJSON()} menuItem>
                            <IconDownload />
                            Export JSON
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive onClick={() => setShowHistory(!showHistory)} menuItem>
                            <IconClock />
                            History
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive onClick={() => openShareModal()} menuItem>
                            <IconShare />
                            Share
                        </ButtonPrimitive>
                    </DropdownMenuItem>

                    {!isLocalOnly && !notebook?.is_template && (
                        <DropdownMenuItem asChild>
                            <ButtonPrimitive
                                onClick={() => {
                                    notebooksModel.actions.deleteNotebook(shortId, notebook?.title)
                                    router.actions.push(urls.notebooks())
                                }}
                                menuItem
                                variant="danger"
                            >
                                <IconTrash />
                                Delete
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                    )}
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
