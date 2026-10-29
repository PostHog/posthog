import { router } from 'kea-router'

import { IconEllipsis } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { getApproveDisabledReason, getChangeRequestButtonVisibility } from 'scenes/approvals/changeRequestsLogic'
import { urls } from 'scenes/urls'

import {
    CHANGE_REQUEST_ACTION_IN_FLIGHT_REASON,
    ChangeRequestActionsProps,
    changeRequestDialogHandlers,
} from './ChangeRequestActions'

export function QuillChangeRequestActions({
    changeRequest,
    onApprove,
    onReject,
    onCancel,
    showViewButton = false,
    showDisabledApproveButton = false,
    actionInFlight = null,
}: ChangeRequestActionsProps): JSX.Element {
    const { showApproveButton, showRejectButton, showCancelButton } = getChangeRequestButtonVisibility(changeRequest)
    const approveDisabledReason = getApproveDisabledReason(changeRequest)
    const inFlightReason = actionInFlight ? CHANGE_REQUEST_ACTION_IN_FLIGHT_REASON : undefined
    const { handleApprove, handleReject, handleCancel } = changeRequestDialogHandlers({
        changeRequest,
        onApprove,
        onReject,
        onCancel,
    })

    return (
        <div className="flex flex-wrap items-center gap-2">
            {showApproveButton ? (
                <Button
                    variant="primary"
                    onClick={handleApprove}
                    loading={actionInFlight === 'approve'}
                    disabledReason={actionInFlight === 'approve' ? undefined : inFlightReason}
                >
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
                <Button
                    variant="outline"
                    onClick={handleReject}
                    loading={actionInFlight === 'reject'}
                    disabledReason={actionInFlight === 'reject' ? undefined : inFlightReason}
                >
                    Reject
                </Button>
            )}
            {showCancelButton && (
                <Button
                    variant="outline"
                    onClick={handleCancel}
                    loading={actionInFlight === 'cancel'}
                    disabledReason={actionInFlight === 'cancel' ? undefined : inFlightReason}
                >
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
