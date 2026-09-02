import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonButton, LemonInputSelect, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { projectLogic } from 'scenes/projectLogic'

import { tagsModel } from '~/models/tagsModel'

export type BulkTagAction = 'add' | 'remove' | 'set'

export interface BulkUpdateTagsResult {
    updated: Array<{ id: number | string; tags: string[] }>
    skipped: Array<{ id: number | string; reason: string }>
}

export type BulkTaggableResource = 'feature_flags' | 'dashboards' | 'insights' | 'event_definitions'

export interface BulkUpdateTagsFormProps {
    resource: BulkTaggableResource
    // Integer PKs for most resources; event definitions are keyed by UUID strings.
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
    const [tagAction, setTagAction] = useState<BulkTagAction>('add')
    const [selectedTags, setSelectedTags] = useState<string[]>([])
    const [loading, setLoading] = useState(false)

    const { tags } = useValues(tagsModel)
    const { loadTags } = useActions(tagsModel)
    const { currentProjectId } = useValues(projectLogic)

    // The form mounts fresh each time its host opens, so this doubles as the on-open refresh.
    useOnMountEffect(() => {
        loadTags()
    })

    const submit = async (): Promise<void> => {
        setLoading(true)
        try {
            const response = (await api.create(`api/projects/${currentProjectId}/${resource}/bulk_update_tags/`, {
                ids: Array.from(selectedIds),
                action: tagAction,
                tags: selectedTags,
            })) as BulkUpdateTagsResult
            const { updated, skipped } = response
            if (skipped.length === 0) {
                lemonToast.success(`Updated tags on ${updated.length} item${updated.length !== 1 ? 's' : ''}`)
            } else {
                lemonToast.warning(
                    `Updated tags on ${updated.length} item${updated.length !== 1 ? 's' : ''}. ${skipped.length} skipped due to permissions.`
                )
            }
            onClose()
            loadTags()
            onSuccess?.(response)
        } catch {
            lemonToast.error('Failed to update tags')
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
            <LemonInputSelect
                mode="multiple"
                allowCustomValues
                value={selectedTags}
                options={(tags as string[]).map((t: string) => ({ key: t, label: t }))}
                onChange={setSelectedTags}
                placeholder="Enter tags..."
                data-attr="bulk-tag-input"
            />
            {tagAction === 'set' && (
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
                        selectedTags.length === 0 && tagAction !== 'set' ? 'Select at least one tag' : undefined
                    }
                >
                    {tagAction === 'add' ? 'Add tags' : tagAction === 'remove' ? 'Remove tags' : 'Replace tags'}
                </LemonButton>
            </div>
        </div>
    )
}
