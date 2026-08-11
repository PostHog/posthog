import { useState } from 'react'

import { IconPencil } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover'

import { BulkTaggableResource, BulkUpdateTagsForm, BulkUpdateTagsResult } from './BulkUpdateTagsForm'

export type { BulkTagAction, BulkTaggableResource, BulkUpdateTagsResult } from './BulkUpdateTagsForm'

interface BulkUpdateTagsButtonProps {
    resource: BulkTaggableResource
    // Integer PKs for most resources; event definitions are keyed by UUID strings.
    selectedIds: ReadonlyArray<number | string>
    onSuccess?: (result: BulkUpdateTagsResult) => void
}

export function BulkUpdateTagsButton({ resource, selectedIds, onSuccess }: BulkUpdateTagsButtonProps): JSX.Element {
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
            <LemonButton type="secondary" size="small" icon={<IconPencil />} onClick={() => setVisible(true)}>
                Update tags
            </LemonButton>
        </Popover>
    )
}
