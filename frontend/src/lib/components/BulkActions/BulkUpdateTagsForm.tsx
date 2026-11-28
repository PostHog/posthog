import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { LemonBanner, LemonButton, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { TagsInputSelect } from 'lib/components/TagsInputSelect'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { projectLogic } from 'scenes/projectLogic'

export type BulkTagAction = 'add' | 'remove' | 'set'

export interface BulkUpdateTagsResult {
    updated: Array<{ id: number | string; tags: string[] }>
    skipped: Array<{ id: number | string; reason: string }>
}

export type BulkTaggableResource =
    | 'feature_flags'
    | 'dashboards'
    | 'insights'
    | 'event_definitions'
    | 'conversations/tickets'
    | 'experiments'

export interface BulkUpdateTagsFormProps {
    resource: BulkTaggableResource
    // Integer PKs for most resources; event definitions and tickets are keyed by UUID strings.
    selectedIds: ReadonlyArray<number | string>
    onSuccess?: (result: BulkUpdateTagsResult) => void
    /** Closes the host (popover or modal). Called on Cancel and after a successful submit. */
    onClose: () => void
    /** Hosts that supply their own title (e.g. a modal) can hide the built-in header line. */
    showHeader?: boolean
    /** The item's current tags. Pass this when editing one item: the form starts with them and saves the result as is. */
    initialTags?: string[]
}

/** The bulk tag editing form, shared between the popover button and the modal host. */
export function BulkUpdateTagsForm({
    resource,
    selectedIds,
    onSuccess,
    onClose,
    showHeader = true,
    initialTags,
}: BulkUpdateTagsFormProps): JSX.Element {
    // With one item's tags known, the user edits them directly, so the add/remove/replace modes are not needed.
    const editsSingleItem = initialTags !== undefined
    const [tagAction, setTagAction] = useState<BulkTagAction>(editsSingleItem ? 'set' : 'add')
    const [selectedTags, setSelectedTags] = useState<string[]>(initialTags ?? [])
    const tagsUnchanged =
        editsSingleItem &&
        selectedTags.length === initialTags.length &&
        selectedTags.every((tag) => initialTags.includes(tag))
    const [loading, setLoading] = useState(false)

    const { currentProjectId } = useValues(projectLogic)

    const submit = async (): Promise<void> => {
        setLoading(true)
        try {
            // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. No generated function covers this endpoint yet. Find out why the generated client skips it (no schema, no product tag, or excluded from the spec) and fix that first.
            const response = (await api.create(`api/projects/${currentProjectId}/${resource}/bulk_update_tags/`, {
                ids: Array.from(selectedIds),
                action: tagAction,
                tags: selectedTags,
            })) as BulkUpdateTagsResult
            const { updated, skipped } = response
            posthog.capture('tags updated', {
                resource,
                action: tagAction,
                tags_count: selectedTags.length,
                requested_count: selectedIds.length,
                processed_count: updated.length,
                skipped_count: skipped.length,
            })
            if (skipped.length === 0) {
                lemonToast.success(`Updated tags on ${updated.length} item${updated.length !== 1 ? 's' : ''}`)
            } else {
                lemonToast.warning(
                    `Updated tags on ${updated.length} item${updated.length !== 1 ? 's' : ''}. ${skipped.length} skipped due to permissions.`
                )
            }
            onClose()
            onSuccess?.(response)
        } catch (error: any) {
            // The server explains rule failures such as a project that requires tags, so show its
            // message rather than a generic one the user cannot act on.
            lemonToast.error(error?.detail || 'Failed to update tags')
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="space-y-3">
            {showHeader && (
                <div className="font-medium text-sm">
                    Update tags for {selectedIds.length} item{selectedIds.length !== 1 ? 's' : ''}
                </div>
            )}
            {!editsSingleItem && (
                <LemonSegmentedButton
                    value={tagAction}
                    onChange={setTagAction}
                    options={[
                        { value: 'add' as const, label: 'Add' },
                        { value: 'remove' as const, label: 'Remove' },
                        { value: 'set' as const, label: 'Replace all' },
                    ]}
                    size="small"
                    fullWidth
                />
            )}
            <TagsInputSelect
                value={selectedTags}
                onChange={setSelectedTags}
                placeholder="Enter tags..."
                data-attr="bulk-tag-input"
            />
            {tagAction === 'set' && !editsSingleItem && (
                <LemonBanner type="warning">This will replace all existing tags on the selected items.</LemonBanner>
            )}
            <div className="flex gap-2 justify-end">
                <LemonButton size="small" type="secondary" onClick={onClose}>
                    Cancel
                </LemonButton>
                <LemonButton
                    size="small"
                    type="primary"
                    onClick={() => void submit()}
                    loading={loading}
                    disabledReason={
                        tagsUnchanged
                            ? 'No changes to save'
                            : selectedTags.length === 0 && tagAction !== 'set'
                              ? 'Select at least one tag'
                              : undefined
                    }
                >
                    {editsSingleItem
                        ? 'Save'
                        : tagAction === 'add'
                          ? 'Add tags'
                          : tagAction === 'remove'
                            ? 'Remove tags'
                            : 'Replace tags'}
                </LemonButton>
            </div>
        </div>
    )
}
