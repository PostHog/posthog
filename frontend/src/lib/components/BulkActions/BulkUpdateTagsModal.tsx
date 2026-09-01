import { LemonModal } from '@posthog/lemon-ui'

import { BulkTaggableResource, BulkUpdateTagsForm, BulkUpdateTagsResult } from './BulkUpdateTagsForm'

export interface BulkUpdateTagsModalProps {
    resource: BulkTaggableResource
    selectedIds: ReadonlyArray<number | string>
    isOpen: boolean
    onClose: () => void
    onSuccess?: (result: BulkUpdateTagsResult) => void
}

/** Modal host for the bulk tag editing form, for surfaces that trigger it from a menu. */
export function BulkUpdateTagsModal({
    resource,
    selectedIds,
    isOpen,
    onClose,
    onSuccess,
}: BulkUpdateTagsModalProps): JSX.Element {
    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title={`Update tags for ${selectedIds.length} item${selectedIds.length === 1 ? '' : 's'}`}
            width={480}
            data-attr="bulk-update-tags-modal"
        >
            <BulkUpdateTagsForm
                resource={resource}
                selectedIds={selectedIds}
                onSuccess={onSuccess}
                onClose={onClose}
                showHeader={false}
            />
        </LemonModal>
    )
}
