import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { TagsInputSelect } from 'lib/components/TagsInputSelect'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'

import {
    BULK_TAG_ACTION_OPTIONS,
    BULK_TAG_REPLACE_WARNING,
    type BulkTaggableResource,
    type BulkUpdateTagsResult,
    useBulkUpdateTags,
} from './useBulkUpdateTags'

export type { BulkTagAction, BulkTaggableResource, BulkUpdateTagsResult } from './useBulkUpdateTags'

export interface BulkUpdateTagsFormProps {
    resource: BulkTaggableResource
    // Integer PKs for most resources; event definitions and tickets are keyed by UUID strings.
    selectedIds: ReadonlyArray<number | string>
    onSuccess?: (result: BulkUpdateTagsResult) => void
    /** Closes the host (popover or modal). Called on Cancel and after a successful submit. */
    onClose: () => void
    /** Hosts that supply their own title (e.g. a modal) can hide the built-in header line. */
    showHeader?: boolean
}

/** The bulk tag editing form, shared between the popover button and the modal host. */
export function BulkUpdateTagsForm({
    resource,
    selectedIds,
    onSuccess,
    onClose,
    showHeader = true,
}: BulkUpdateTagsFormProps): JSX.Element {
    const {
        tagAction,
        setTagAction,
        selectedTags,
        setSelectedTags,
        loading,
        submit,
        submitLabel,
        submitDisabledReason,
    } = useBulkUpdateTags({ resource, selectedIds, onSuccess, onClose })

    return (
        <div className="space-y-3">
            {showHeader && (
                <div className="font-medium text-sm">
                    Update tags for {selectedIds.length} item{selectedIds.length !== 1 ? 's' : ''}
                </div>
            )}
            <LemonSegmentedButton
                value={tagAction}
                onChange={setTagAction}
                options={BULK_TAG_ACTION_OPTIONS}
                size="small"
                fullWidth
            />
            <TagsInputSelect
                value={selectedTags}
                onChange={setSelectedTags}
                placeholder="Enter tags..."
                data-attr="bulk-tag-input"
            />
            {tagAction === 'set' && <LemonBanner type="warning">{BULK_TAG_REPLACE_WARNING}</LemonBanner>}
            <div className="flex gap-2 justify-end">
                <LemonButton size="small" type="secondary" onClick={onClose}>
                    Cancel
                </LemonButton>
                <LemonButton
                    size="small"
                    type="primary"
                    onClick={() => void submit()}
                    loading={loading}
                    disabledReason={submitDisabledReason}
                >
                    {submitLabel}
                </LemonButton>
            </div>
        </div>
    )
}
