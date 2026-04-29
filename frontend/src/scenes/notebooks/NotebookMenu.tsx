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
import { notebookGuestPolicyLogic } from 'scenes/guest/notebookGuestPolicyLogic'
import { urls } from 'scenes/urls'

import { notebooksModel } from '~/models/notebooksModel'

import { NotebookLogicProps, notebookLogic } from './Notebook/notebookLogic'

export function NotebookMenu({ shortId }: NotebookLogicProps): JSX.Element | null {
    const { notebook, showHistory, isLocalOnly } = useValues(notebookLogic({ shortId }))
    const { openShareModal, duplicateNotebook, exportJSON, setShowHistory } = useActions(notebookLogic({ shortId }))
    const notebookGuestPolicy = useValues(notebookGuestPolicyLogic({ shortId }))

    // Single roll-up gate: collapses the whole 3-dot menu when no admin verb is allowed.
    // For non-guests this stays true, so the menu always renders. For guest viewers this
    // is false, so the menu trigger never renders.
    if (!notebookGuestPolicy.canPerformActions) {
        return null
    }

    const shouldRenderDuplicateButton = notebookGuestPolicy.canDuplicate
    const shouldRenderExportJsonButton = notebookGuestPolicy.canExportJSON
    const shouldRenderHistoryButton = notebookGuestPolicy.canViewHistory
    const shouldRenderShareButton = notebookGuestPolicy.canShare
    const shouldRenderDeleteButton = notebookGuestPolicy.canDelete && !isLocalOnly && !notebook?.is_template

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive iconOnly>
                    <IconEllipsis className="text-tertiary size-3 group-hover:text-primary z-10" />
                </ButtonPrimitive>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="center" side="bottom">
                <DropdownMenuGroup>
                    {shouldRenderDuplicateButton && (
                        <DropdownMenuItem asChild>
                            <ButtonPrimitive onClick={() => duplicateNotebook()} menuItem>
                                <IconCopy />
                                Duplicate
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                    )}
                    {shouldRenderExportJsonButton && (
                        <DropdownMenuItem asChild>
                            <ButtonPrimitive onClick={() => exportJSON()} menuItem>
                                <IconDownload />
                                Export JSON
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                    )}
                    {shouldRenderHistoryButton && (
                        <DropdownMenuItem asChild>
                            <ButtonPrimitive onClick={() => setShowHistory(!showHistory)} menuItem>
                                <IconClock />
                                History
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                    )}
                    {shouldRenderShareButton && (
                        <DropdownMenuItem asChild>
                            <ButtonPrimitive onClick={() => openShareModal()} menuItem>
                                <IconShare />
                                Share
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                    )}

                    {shouldRenderDeleteButton && (
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
