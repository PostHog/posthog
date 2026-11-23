import { router } from 'kea-router'

import { IconEllipsis } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { changeRequestDialogHandlers } from 'scenes/approvals/ChangeRequestActions'
import { getChangeRequestButtonVisibility } from 'scenes/approvals/changeRequestsLogic'
import { urls } from 'scenes/urls'

import { ChangeRequestTableActionsProps } from './ChangeRequestTableActions'

export function QuillChangeRequestTableActions({
    changeRequest,
    onApprove,
    onReject,
}: ChangeRequestTableActionsProps): JSX.Element {
    const { showApproveButton, showRejectButton } = getChangeRequestButtonVisibility(changeRequest)
    const { handleApprove, handleReject } = changeRequestDialogHandlers({ changeRequest, onApprove, onReject })

    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={<Button size="icon" aria-label="More actions" tooltip="More actions" />}>
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => router.actions.push(urls.approval(changeRequest.id))}>
                    View details
                </DropdownMenuItem>
                {showApproveButton && <DropdownMenuItem onClick={handleApprove}>Approve</DropdownMenuItem>}
                {showRejectButton && (
                    <DropdownMenuItem variant="destructive" onClick={handleReject}>
                        Reject
                    </DropdownMenuItem>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
