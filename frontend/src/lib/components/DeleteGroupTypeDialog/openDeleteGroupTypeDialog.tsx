import { LemonDialog, Link } from '@posthog/lemon-ui'

export interface DeleteGroupTypeDialogProps {
    onConfirm: () => void
    groupTypeName: string
}

export function openDeleteGroupTypeDialog({ onConfirm, groupTypeName }: DeleteGroupTypeDialogProps): void {
    const groupType = groupTypeName.toLowerCase()
    LemonDialog.open({
        title: `Delete ${groupType} group type`,
        description: (
            <div className="mt-2 w-150">
                Deleting a group type is irreversible.
                <br />
                <br />
                You will not be able to assign existing events from this group type to another group type created in the
                future, only new events.
                <br />
                <br />
                For more information about groups, see{' '}
                <Link to="https://posthog.com/docs/product-analytics/group-analytics" target="_blank">
                    the docs
                </Link>
            </div>
        ),
        secondaryButton: {
            type: 'secondary',
            children: 'Cancel',
        },
        primaryButton: {
            type: 'primary',
            status: 'danger',
            onClick: onConfirm,
            children: `Delete ${groupType}`,
        },
    })
}
