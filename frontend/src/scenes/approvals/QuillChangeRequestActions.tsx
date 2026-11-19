import { router } from 'kea-router'

import { IconEllipsis } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { getApproveDisabledReason, getChangeRequestButtonVisibility } from 'scenes/approvals/changeRequestsLogic'
import { urls } from 'scenes/urls'

import { ChangeRequestActionsProps, changeRequestDialogHandlers } from './ChangeRequestActions'

export function QuillChangeRequestActions({
    changeRequest,
    onApprove,
    onReject,
    onCancel,
    showViewButton = false,
    showDisabledApproveButton = false,
}: ChangeRequestActionsProps): JSX.Element {
    const { showApproveButton, showRejectButton, showCancelButton } = getChangeRequestButtonVisibility(changeRequest)
    const approveDisabledReason = getApproveDisabledReason(changeRequest)
    const { handleApprove, handleReject, handleCancel } = changeRequestDialogHandlers({
        changeRequest,
        onApprove,
        onReject,
        onCancel,
    })

    return (
        <div className="flex flex-wrap items-center gap-2">
            {showApproveButton ? (
                <Button variant="primary" onClick={handleApprove}>
                    Approve
                </Button>
            ) : (
                showDisabledApproveButton &&
                approveDisabledReason && (
                    <Button variant="primary" disabledReason={approveDisabledReason}>
                        Approve
                    </Button>
                )
            )}
            {showRejectButton && (
                <Button variant="outline" onClick={handleReject}>
                    Reject
                </Button>
            )}
            {showCancelButton && (
                <Button variant="outline" onClick={handleCancel}>
                    Cancel
                </Button>
            )}
            {showViewButton && (
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={<Button variant="outline" size="icon" aria-label="More" tooltip="More" />}
                    >
                        <IconEllipsis />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => router.actions.push(urls.approval(changeRequest.id))}>
                            View details
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
        </div>
    )
}
