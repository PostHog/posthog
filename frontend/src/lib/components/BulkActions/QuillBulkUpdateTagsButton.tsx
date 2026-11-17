import { useId, useState } from 'react'

import { IconPencil } from '@posthog/icons'
import {
    Button,
    Item,
    ItemContent,
    ItemDescription,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Text,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'
import { useTagPages } from 'lib/components/useTagPages'
import { pluralize } from 'lib/utils/strings'

import {
    BULK_TAG_ACTION_OPTIONS,
    BULK_TAG_REPLACE_WARNING,
    type BulkTagAction,
    type BulkTaggableResource,
    type BulkUpdateTagsResult,
    useBulkUpdateTags,
} from './useBulkUpdateTags'

function QuillBulkUpdateTagsForm({
    resource,
    selectedIds,
    onSuccess,
    onClose,
}: {
    resource: BulkTaggableResource
    selectedIds: ReadonlyArray<number | string>
    onSuccess?: (result: BulkUpdateTagsResult) => void
    onClose: () => void
}): JSX.Element {
    const form = useBulkUpdateTags({ resource, selectedIds, onSuccess, onClose })
    const tagPages = useTagPages(useId())

    return (
        <div className="flex flex-col gap-3">
            <Text size="xs" weight="medium">
                Update tags for {pluralize(selectedIds.length, 'item')}
            </Text>
            <ToggleGroup
                variant="outline"
                aria-label="Tag action"
                className="w-full"
                value={[form.tagAction]}
                onValueChange={(next: string[]) => {
                    const picked = next[0] as BulkTagAction | undefined
                    if (picked) {
                        form.setTagAction(picked)
                    }
                }}
            >
                {BULK_TAG_ACTION_OPTIONS.map((option) => (
                    <ToggleGroupItem key={option.value} value={option.value} className="flex-1">
                        {option.label}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
            <TagsCombobox
                value={form.selectedTags}
                onChange={form.setSelectedTags}
                options={tagPages.tags.map(({ tag }) => tag).filter((tag) => !form.selectedTags.includes(tag))}
                loading={tagPages.awaitingFirstPage || tagPages.pageLoading}
                onOpen={() => tagPages.setOpen(true)}
                onClose={() => tagPages.setOpen(false)}
                onInputChange={tagPages.setSearch}
                error={tagPages.error ? "Couldn't load tags." : undefined}
                onRetry={tagPages.retry}
                onScrollEnd={tagPages.loadMore}
                loadingMore={tagPages.pageLoading && tagPages.tags.length > 0}
                placeholder="Enter tags..."
                allowCustomValues
                customValueNoun="tag"
                disabled={form.loading}
                dataAttr="bulk-tag-input"
            />
            {form.tagAction === 'set' && (
                <Item variant="outline" size="sm" tone="warning">
                    <ItemContent>
                        <ItemDescription>{BULK_TAG_REPLACE_WARNING}</ItemDescription>
                    </ItemContent>
                </Item>
            )}
            <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={onClose} disabled={form.loading}>
                    Cancel
                </Button>
                <Button
                    variant="primary"
                    onClick={() => void form.submit()}
                    loading={form.loading}
                    disabledReason={form.submitDisabledReason}
                >
                    {form.submitLabel}
                </Button>
            </div>
        </div>
    )
}

/** The quill twin of BulkUpdateTagsButton: an "Update tags" button that opens the bulk tag form in a popover. */
export function QuillBulkUpdateTagsButton({
    resource,
    selectedIds,
    onSuccess,
    disabledReason,
    tooltip,
}: {
    resource: BulkTaggableResource
    selectedIds: ReadonlyArray<number | string>
    onSuccess?: (result: BulkUpdateTagsResult) => void
    disabledReason?: string
    tooltip?: string
}): JSX.Element {
    const [open, setOpen] = useState(false)

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger
                render={
                    <Button
                        variant="outline"
                        disabledReason={disabledReason}
                        tooltip={tooltip}
                        data-attr="bulk-update-tags"
                    />
                }
            >
                <IconPencil />
                Update tags
            </PopoverTrigger>
            <PopoverContent align="end" className="w-80 p-3">
                {open && (
                    <QuillBulkUpdateTagsForm
                        resource={resource}
                        selectedIds={selectedIds}
                        onSuccess={onSuccess}
                        onClose={() => setOpen(false)}
                    />
                )}
            </PopoverContent>
        </Popover>
    )
}
