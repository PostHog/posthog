import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconPencil } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover'
import { BulkTaggableResource, listSelectionLogic } from 'lib/logic/listSelectionLogic'

import { BulkUpdateTagsPopover } from './BulkUpdateTagsPopover'

export function BulkActionToolbar({
    resource,
    children,
}: {
    resource: BulkTaggableResource
    children?: ReactNode
}): JSX.Element | null {
    const logic = listSelectionLogic({ resource })
    const { selectedCount, bulkTagsPopoverVisible, bulkUpdateTagsResponseLoading } = useValues(logic)
    const { clearSelection, showBulkTagsPopover, hideBulkTagsPopover } = useActions(logic)

    if (selectedCount === 0) {
        return null
    }

    return (
        <div className="flex items-center gap-2">
            <span className="text-muted text-sm">
                {selectedCount} item{selectedCount !== 1 ? 's' : ''} selected
            </span>
            <LemonButton type="secondary" size="small" onClick={clearSelection}>
                Clear
            </LemonButton>
            <Popover
                visible={bulkTagsPopoverVisible}
                onClickOutside={hideBulkTagsPopover}
                overlay={<BulkUpdateTagsPopover resource={resource} />}
                placement="bottom-end"
            >
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPencil />}
                    onClick={showBulkTagsPopover}
                    loading={bulkUpdateTagsResponseLoading}
                >
                    Update tags
                </LemonButton>
            </Popover>
            {children}
        </div>
    )
}
