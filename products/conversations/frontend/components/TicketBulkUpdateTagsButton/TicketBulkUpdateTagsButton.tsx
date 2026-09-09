import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPencil } from '@posthog/icons'
import { lemonToast } from '@posthog/lemon-ui'

import { ApiError } from 'lib/api-error'
import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { Button, Popover, PopoverContent, PopoverTrigger, Text, ToggleGroup, ToggleGroupItem } from 'lib/ui/quill'
import { projectLogic } from 'scenes/projectLogic'

import { tagsModel } from '~/models/tagsModel'

import { conversationsTicketsBulkUpdateTagsCreate } from '../../generated/api'
import type { BulkUpdateTagsActionEnumApi } from '../../generated/api.schemas'

interface TicketBulkUpdateTagsButtonProps {
    selectedIds: readonly string[]
    onSuccess?: () => void
    disabledReason?: string
    tooltip?: string
}

export function TicketBulkUpdateTagsButton({
    selectedIds,
    onSuccess,
    disabledReason,
    tooltip,
}: TicketBulkUpdateTagsButtonProps): JSX.Element {
    const [open, setOpen] = useState(false)

    const trigger = (
        <Button
            variant="outline"
            size="sm"
            disabled={!!disabledReason}
            title={disabledReason ?? tooltip}
            aria-label="Update tags"
        >
            <IconPencil />
            Update tags
        </Button>
    )

    if (disabledReason) {
        return trigger
    }

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger render={trigger} />
            <PopoverContent align="end" className="w-80 p-3">
                <TicketBulkUpdateTagsForm
                    selectedIds={selectedIds}
                    onSuccess={onSuccess}
                    onClose={() => setOpen(false)}
                />
            </PopoverContent>
        </Popover>
    )
}

function TicketBulkUpdateTagsForm({
    selectedIds,
    onSuccess,
    onClose,
}: {
    selectedIds: readonly string[]
    onSuccess?: () => void
    onClose: () => void
}): JSX.Element {
    const [tagAction, setTagAction] = useState<BulkUpdateTagsActionEnumApi>('add')
    const [selectedTags, setSelectedTags] = useState<string[]>([])
    const [loading, setLoading] = useState(false)

    const { tags } = useValues(tagsModel)
    const { loadTags } = useActions(tagsModel)
    const { currentProjectId } = useValues(projectLogic)

    useOnMountEffect(() => {
        loadTags()
    })

    const submitDisabledReason =
        selectedTags.length === 0 && tagAction !== 'set' ? 'Select at least one tag' : undefined

    const submit = async (): Promise<void> => {
        if (!currentProjectId || loading || submitDisabledReason) {
            return
        }
        setLoading(true)
        try {
            const { updated, skipped } = await conversationsTicketsBulkUpdateTagsCreate(String(currentProjectId), {
                ids: [...selectedIds],
                action: tagAction,
                tags: selectedTags,
            })
            if (skipped.length === 0) {
                lemonToast.success(`Updated tags on ${updated.length} item${updated.length !== 1 ? 's' : ''}`)
            } else {
                lemonToast.warning(
                    `Updated tags on ${updated.length} item${updated.length !== 1 ? 's' : ''}. ${skipped.length} skipped due to permissions.`
                )
            }
            onClose()
            loadTags()
            onSuccess?.()
        } catch (error) {
            // The server explains rule failures such as a project that requires tags, so show its
            // message rather than a generic one the user cannot act on.
            lemonToast.error(error instanceof ApiError ? (error.detail ?? error.message) : 'Failed to update tags')
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="flex flex-col gap-3">
            <Text size="sm" weight="medium">
                Update tags for {selectedIds.length} item{selectedIds.length !== 1 ? 's' : ''}
            </Text>
            <ToggleGroup
                variant="outline"
                size="sm"
                className="w-full"
                value={[tagAction]}
                onValueChange={([value]) => {
                    if (value === 'add' || value === 'remove' || value === 'set') {
                        setTagAction(value)
                    }
                }}
            >
                <ToggleGroupItem value="add" className="flex-1">
                    Add
                </ToggleGroupItem>
                <ToggleGroupItem value="remove" className="flex-1">
                    Remove
                </ToggleGroupItem>
                <ToggleGroupItem value="set" className="flex-1">
                    Replace all
                </ToggleGroupItem>
            </ToggleGroup>
            <TagsCombobox
                value={selectedTags}
                onChange={setSelectedTags}
                options={tags}
                placeholder="Enter tags..."
                dataAttr="bulk-tag-input"
            />
            {tagAction === 'set' ? (
                <Text size="xs" className="text-warning">
                    This will replace all existing tags on the selected items.
                </Text>
            ) : null}
            <div className="flex justify-end gap-2">
                <Button variant="outline" size="sm" onClick={onClose}>
                    Cancel
                </Button>
                <Button
                    variant="primary"
                    size="sm"
                    loading={loading}
                    disabled={loading || !!submitDisabledReason}
                    title={submitDisabledReason}
                    onClick={() => void submit()}
                >
                    {tagAction === 'add' ? 'Add tags' : tagAction === 'remove' ? 'Remove tags' : 'Replace tags'}
                </Button>
            </div>
        </div>
    )
}
