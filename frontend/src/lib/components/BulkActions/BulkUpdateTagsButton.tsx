import { useState } from 'react'

import { IconPencil } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover'

import { BulkTaggableResource, BulkUpdateTagsForm, BulkUpdateTagsResult } from './BulkUpdateTagsForm'

export type { BulkTagAction, BulkTaggableResource, BulkUpdateTagsResult } from './BulkUpdateTagsForm'

interface BulkUpdateTagsButtonProps {
    resource: BulkTaggableResource
    // Integer PKs for most resources; event definitions and tickets are keyed by UUID strings.
    selectedIds: ReadonlyArray<number | string>
    onSuccess?: (result: BulkUpdateTagsResult) => void
    /** Disables the trigger with an explanatory tooltip, for toolbars that render it before any selection exists. */
    disabledReason?: string
    /** Tooltip on the enabled trigger, e.g. a partial-selection warning. */
    tooltip?: string
}

export function BulkUpdateTagsButton({
    resource,
    selectedIds,
    onSuccess,
    disabledReason,
    tooltip,
}: BulkUpdateTagsButtonProps): JSX.Element {
    const [visible, setVisible] = useState(false)

    return (
        <Popover
            visible={visible}
            onClickOutside={() => setVisible(false)}
            placement="bottom-end"
            overlay={
                <div className="p-3 w-80">
                    <BulkUpdateTagsForm
                        resource={resource}
                        selectedIds={selectedIds}
                        onSuccess={onSuccess}
                        onClose={() => setVisible(false)}
                    />
                </div>
            }
        >
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconPencil />}
                onClick={() => setVisible(true)}
                disabledReason={disabledReason}
                tooltip={tooltip}
            >
                Update tags
            </LemonButton>
        </Popover>
    )
}
