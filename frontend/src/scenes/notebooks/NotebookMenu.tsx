import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconClock, IconCopy, IconDownload, IconEllipsis, IconShare, IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { notebooksModel } from '~/models/notebooksModel'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { NotebookLogicProps, notebookLogic } from './Notebook/notebookLogic'

export function NotebookMenu({ shortId }: NotebookLogicProps): JSX.Element {
    const { notebook, showHistory, isLocalOnly, isTemplate } = useValues(notebookLogic({ shortId }))
    const { openShareModal, duplicateNotebook, exportJSON, setShowHistory } = useActions(notebookLogic({ shortId }))
    const isRemovingSidePanelFlag = useFeatureFlag('UX_REMOVE_SIDEPANEL')

    if (isRemovingSidePanelFlag) {
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

    return (
        <LemonMenu
            items={[
                !isTemplate && {
                    label: 'Duplicate',
                    icon: <IconCopy />,
                    onClick: () => duplicateNotebook(),
                },
                {
                    label: 'Export JSON',
                    icon: <IconDownload />,
                    onClick: () => exportJSON(),
                },
                {
                    label: 'History',
                    icon: <IconClock />,
                    onClick: () => setShowHistory(!showHistory),
                },
                {
                    label: 'Share',
                    icon: <IconShare />,
                    onClick: () => openShareModal(),
                },
                !isLocalOnly &&
                    !notebook?.is_template && {
                        label: 'Delete',
                        icon: <IconTrash />,
                        status: 'danger',
                        disabledReason:
                            !notebook?.user_access_level ||
                            !accessLevelSatisfied(
                                AccessControlResourceType.Notebook,
                                notebook.user_access_level,
                                AccessControlLevel.Editor
                            )
                                ? 'You do not have permission to delete this notebook.'
                                : undefined,
                        onClick: () => {
                            notebooksModel.actions.deleteNotebook(shortId, notebook?.title)
                            router.actions.push(urls.notebooks())
                        },
                    },
                {
                    label: () => (
                        <UserActivityIndicator at={notebook?.last_modified_at} by={notebook?.last_modified_by} />
                    ),
                    key: 'sync-info',
                },
            ]}
        >
            <LemonButton aria-label="more" icon={<IconEllipsis />} size="small" />
        </LemonMenu>
    )
}
