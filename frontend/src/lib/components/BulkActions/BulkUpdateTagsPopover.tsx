import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInputSelect } from '@posthog/lemon-ui'

import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { BulkTaggableResource, listSelectionLogic } from 'lib/logic/listSelectionLogic'

import { tagsModel } from '~/models/tagsModel'

export function BulkUpdateTagsPopover({ resource }: { resource: BulkTaggableResource }): JSX.Element {
    const { tags } = useValues(tagsModel)

    const logic = listSelectionLogic({ resource })
    const { bulkUpdateTagsResponseLoading, selectedCount, popoverTagAction, popoverSelectedTags } = useValues(logic)
    const { bulkUpdateTags, hideBulkTagsPopover, setPopoverTagAction, setPopoverSelectedTags } = useActions(logic)

    const handleSubmit = (): void => {
        bulkUpdateTags({ action: popoverTagAction, tags: popoverSelectedTags })
    }

    return (
        <div className="p-3 space-y-3 w-80">
            <div className="font-medium text-sm">
                Update tags for {selectedCount} item{selectedCount !== 1 ? 's' : ''}
            </div>

            <LemonSegmentedButton
                value={popoverTagAction}
                onChange={setPopoverTagAction}
                options={[
                    { value: 'add' as const, label: 'Add' },
                    { value: 'remove' as const, label: 'Remove' },
                    { value: 'set' as const, label: 'Replace all' },
                ]}
                size="small"
                fullWidth
            />

            <LemonInputSelect
                mode="multiple"
                allowCustomValues
                value={popoverSelectedTags}
                options={tags.map((t) => ({ key: t, label: t }))}
                onChange={setPopoverSelectedTags}
                placeholder="Enter tags..."
                data-attr="bulk-tag-input"
            />

            {popoverTagAction === 'set' && (
                <LemonBanner type="warning">This will replace all existing tags on the selected items.</LemonBanner>
            )}

            <div className="flex gap-2 justify-end">
                <LemonButton size="small" type="secondary" onClick={hideBulkTagsPopover}>
                    Cancel
                </LemonButton>
                <LemonButton
                    size="small"
                    type="primary"
                    onClick={handleSubmit}
                    loading={bulkUpdateTagsResponseLoading}
                    disabledReason={
                        popoverSelectedTags.length === 0 && popoverTagAction !== 'set'
                            ? 'Select at least one tag'
                            : undefined
                    }
                >
                    {popoverTagAction === 'add'
                        ? 'Add tags'
                        : popoverTagAction === 'remove'
                          ? 'Remove tags'
                          : 'Replace tags'}
                </LemonButton>
            </div>
        </div>
    )
}
