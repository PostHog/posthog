import { LemonInput, LemonInputSelect } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'

import type { TagUsageApi } from '~/generated/core/api.schemas'

import { otherObjectCount, ticketCount } from './supportTagsLogic'

function usageSentence(tag: TagUsageApi): string {
    const tickets = ticketCount(tag)
    const others = otherObjectCount(tag)
    const ticketPart = `${tickets} ${tickets === 1 ? 'ticket' : 'tickets'}`
    return others === 0 ? ticketPart : `${ticketPart} and ${others} other ${others === 1 ? 'object' : 'objects'}`
}

export function openRenameTagDialog(tag: TagUsageApi, onRename: (name: string) => void): void {
    LemonDialog.openForm({
        title: `Rename "${tag.name}"`,
        description: `The new name applies to ${usageSentence(tag)}.`,
        initialValues: { name: tag.name },
        errors: { name: (name: string) => (name?.trim() ? undefined : 'Enter a tag name') },
        content: (
            <LemonField name="name" label="New name">
                <LemonInput data-attr="support-tag-rename-input" autoFocus />
            </LemonField>
        ),
        onSubmit: ({ name }) => onRename(name),
    })
}

export function openMergeTagDialog(
    tag: TagUsageApi,
    otherTags: TagUsageApi[],
    onMerge: (intoId: string) => void
): void {
    LemonDialog.openForm({
        title: `Merge "${tag.name}"`,
        description: `Everything tagged "${tag.name}" moves onto the tag you pick, and "${tag.name}" is deleted.`,
        initialValues: { intoId: [] as string[] },
        errors: { intoId: (intoId: string[]) => (intoId?.length ? undefined : 'Pick a tag to merge into') },
        content: (
            <LemonField name="intoId" label="Merge into">
                <LemonInputSelect
                    mode="single"
                    placeholder="Search tags"
                    data-attr="support-tag-merge-target"
                    options={otherTags.map((other) => ({ key: other.id, label: other.name }))}
                />
            </LemonField>
        ),
        onSubmit: ({ intoId }) => onMerge(intoId[0]),
    })
}

export function openDeleteTagDialog(tag: TagUsageApi, onDelete: () => void): void {
    LemonDialog.open({
        title: `Delete "${tag.name}"?`,
        description: `This removes the tag from ${usageSentence(tag)}. Nothing else is deleted.`,
        primaryButton: {
            children: 'Delete',
            status: 'danger',
            'data-attr': 'support-tag-delete-confirm',
            onClick: onDelete,
        },
        secondaryButton: { children: 'Cancel' },
    })
}
