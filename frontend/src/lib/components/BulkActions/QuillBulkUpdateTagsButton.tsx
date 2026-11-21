import { useState } from 'react'

import { IconPencil } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { BulkTaggableResource, BulkUpdateTagsResult } from './BulkUpdateTagsForm'
import { BulkUpdateTagsModal } from './BulkUpdateTagsModal'

interface QuillBulkUpdateTagsButtonProps {
    resource: BulkTaggableResource
    // Integer PKs for most resources; event definitions and tickets are keyed by UUID strings.
    selectedIds: ReadonlyArray<number | string>
    onSuccess?: (result: BulkUpdateTagsResult) => void
    /** Disables the trigger with an explanatory tooltip. */
    disabledReason?: string
    /** Tooltip on the enabled trigger, e.g. a partial-selection warning. */
    tooltip?: string
}

/** The quill trigger for bulk tag editing. It opens the same form as `BulkUpdateTagsButton`, in its modal host. */
export function QuillBulkUpdateTagsButton({
    resource,
    selectedIds,
    onSuccess,
    disabledReason,
    tooltip,
}: QuillBulkUpdateTagsButtonProps): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)

    return (
        <>
            <Button
                variant="outline"
                onClick={() => setIsOpen(true)}
                disabledReason={disabledReason}
                tooltip={tooltip}
                data-attr="bulk-update-tags-button"
            >
                <IconPencil />
                Update tags
            </Button>
            <BulkUpdateTagsModal
                resource={resource}
                selectedIds={selectedIds}
                isOpen={isOpen}
                onClose={() => setIsOpen(false)}
                onSuccess={onSuccess}
            />
        </>
    )
}
