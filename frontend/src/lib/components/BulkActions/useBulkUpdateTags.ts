import { useValues } from 'kea'
import { useState } from 'react'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
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

export interface UseBulkUpdateTagsProps {
    resource: BulkTaggableResource
    // Integer PKs for most resources; event definitions and tickets are keyed by UUID strings.
    selectedIds: ReadonlyArray<number | string>
    onSuccess?: (result: BulkUpdateTagsResult) => void
    /** Closes the host (popover or modal). Called on Cancel and after a successful submit. */
    onClose: () => void
}

export interface BulkUpdateTags {
    tagAction: BulkTagAction
    setTagAction: (action: BulkTagAction) => void
    selectedTags: string[]
    setSelectedTags: (tags: string[]) => void
    loading: boolean
    submit: () => Promise<void>
    submitLabel: string
    submitDisabledReason: string | undefined
}

export const BULK_TAG_ACTION_OPTIONS: { value: BulkTagAction; label: string }[] = [
    { value: 'add', label: 'Add' },
    { value: 'remove', label: 'Remove' },
    { value: 'set', label: 'Replace all' },
]

export const BULK_TAG_REPLACE_WARNING = 'This will replace all existing tags on the selected items.'

/** The state and request of the bulk tag form, shared by the Lemon and quill hosts. */
export function useBulkUpdateTags({
    resource,
    selectedIds,
    onSuccess,
    onClose,
}: UseBulkUpdateTagsProps): BulkUpdateTags {
    const [tagAction, setTagAction] = useState<BulkTagAction>('add')
    const [selectedTags, setSelectedTags] = useState<string[]>([])
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

    return {
        tagAction,
        setTagAction,
        selectedTags,
        setSelectedTags,
        loading,
        submit,
        submitLabel: tagAction === 'add' ? 'Add tags' : tagAction === 'remove' ? 'Remove tags' : 'Replace tags',
        submitDisabledReason: selectedTags.length === 0 && tagAction !== 'set' ? 'Select at least one tag' : undefined,
    }
}
