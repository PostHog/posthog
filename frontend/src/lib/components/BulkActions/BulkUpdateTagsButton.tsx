import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPencil } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInputSelect, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { Popover } from 'lib/lemon-ui/Popover'
import { projectLogic } from 'scenes/projectLogic'

import { tagsModel } from '~/models/tagsModel'

export type BulkTagAction = 'add' | 'remove' | 'set'

export interface BulkUpdateTagsResult {
    updated: Array<{ id: number; tags: string[] }>
    skipped: Array<{ id: number; reason: string }>
}

export type BulkTaggableResource = 'feature_flags' | 'dashboards' | 'insights'

interface BulkUpdateTagsButtonProps {
    resource: BulkTaggableResource
    selectedIds: ReadonlyArray<number>
    onSuccess?: () => void
}

export function BulkUpdateTagsButton({ resource, selectedIds, onSuccess }: BulkUpdateTagsButtonProps): JSX.Element {
    const [visible, setVisible] = useState(false)
    const [tagAction, setTagAction] = useState<BulkTagAction>('add')
    const [selectedTags, setSelectedTags] = useState<string[]>([])
    const [loading, setLoading] = useState(false)

    const { tags } = useValues(tagsModel)
    const { loadTags } = useActions(tagsModel)
    const { currentProjectId } = useValues(projectLogic)

    const open = (): void => {
        loadTags()
        setVisible(true)
    }

    const close = (): void => {
        setVisible(false)
        setTagAction('add')
        setSelectedTags([])
    }

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
            close()
            loadTags()
            onSuccess?.()
        } catch {
            lemonToast.error('Failed to update tags')
        } finally {
            setLoading(false)
        }
    }

    return (
        <Popover
            visible={visible}
            onClickOutside={close}
            placement="bottom-end"
            overlay={
                <div className="p-3 space-y-3 w-80">
                    <div className="font-medium text-sm">
                        Update tags for {selectedIds.length} item{selectedIds.length !== 1 ? 's' : ''}
                    </div>
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
                        <LemonBanner type="warning">
                            This will replace all existing tags on the selected items.
                        </LemonBanner>
                    )}
                    <div className="flex gap-2 justify-end">
                        <LemonButton size="small" type="secondary" onClick={close}>
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
            }
        >
            <LemonButton type="secondary" size="small" icon={<IconPencil />} onClick={open}>
                Update tags
            </LemonButton>
        </Popover>
    )
}
