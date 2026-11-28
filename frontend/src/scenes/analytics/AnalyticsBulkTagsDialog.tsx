import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldLabel,
} from '@posthog/quill'

import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'
import { useTagPages } from 'lib/components/useTagPages'
import { pluralize } from 'lib/utils/strings'

import { analyticsSelectionLogic } from './analyticsSelectionLogic'

/** Adds tags to, or removes them from, every selected dashboard and insight in the Analytics list. */
export function AnalyticsBulkTagsDialog(): JSX.Element {
    const { bulkTagsAction, bulkTagsSaving, selectedItems, taggableSelectedItems, selectedTags } =
        useValues(analyticsSelectionLogic)
    const { closeBulkTags, applyBulkTags } = useActions(analyticsSelectionLogic)
    const [tags, setTags] = useState<string[]>([])
    const tagPages = useTagPages('analytics-bulk-tags')
    const adding = bulkTagsAction === 'add'
    const taggableCount = taggableSelectedItems.length
    const untouchedCount = selectedItems.length - taggableCount

    // Each open starts empty, and a failed save keeps the picks so the person can try again.
    useEffect(() => {
        if (bulkTagsAction) {
            setTags([])
        }
    }, [bulkTagsAction])

    return (
        <Dialog open={!!bulkTagsAction} onOpenChange={(open: boolean) => !open && closeBulkTags()}>
            <DialogContent data-attr="analytics-bulk-tags-dialog">
                <form
                    className="contents"
                    onSubmit={(event) => {
                        event.preventDefault()
                        if (tags.length && !bulkTagsSaving) {
                            applyBulkTags(tags)
                        }
                    }}
                >
                    <DialogHeader>
                        <DialogTitle>
                            {adding
                                ? `Add tags to ${pluralize(taggableCount, 'item')}`
                                : `Remove tags from ${pluralize(taggableCount, 'item')}`}
                        </DialogTitle>
                        <DialogDescription>
                            {untouchedCount
                                ? `Only dashboards and insights have tags, so the other ${pluralize(untouchedCount, 'selected item')} stay as they are.`
                                : adding
                                  ? 'Each item keeps the tags it has, and gets these too.'
                                  : 'Each item keeps its other tags.'}
                        </DialogDescription>
                    </DialogHeader>
                    <DialogBody>
                        <Field>
                            <FieldLabel>Tags</FieldLabel>
                            {adding ? (
                                <TagsCombobox
                                    value={tags}
                                    onChange={setTags}
                                    options={tagPages.tags.map(({ tag }) => tag).filter((tag) => !tags.includes(tag))}
                                    onOpen={() => tagPages.setOpen(true)}
                                    onClose={() => tagPages.setOpen(false)}
                                    onInputChange={tagPages.setSearch}
                                    loading={tagPages.awaitingFirstPage}
                                    error={tagPages.error ? 'Couldn’t load tags.' : undefined}
                                    onRetry={tagPages.retry}
                                    onScrollEnd={tagPages.loadMore}
                                    loadingMore={tagPages.pageLoading && tagPages.tags.length > 0}
                                    placeholder="Add tags..."
                                    allowCustomValues
                                    customValueNoun="tag"
                                    autoFocus
                                    dataAttr="analytics-bulk-tags-input"
                                />
                            ) : (
                                <TagsCombobox
                                    value={tags}
                                    onChange={setTags}
                                    options={selectedTags.filter((tag) => !tags.includes(tag))}
                                    placeholder="Pick tags to remove..."
                                    allowCustomValues={false}
                                    customValueNoun="tag"
                                    autoFocus
                                    dataAttr="analytics-bulk-tags-input"
                                />
                            )}
                        </Field>
                    </DialogBody>
                    <DialogFooter>
                        <DialogClose render={<Button variant="outline" data-attr="analytics-bulk-tags-cancel" />}>
                            Cancel
                        </DialogClose>
                        <Button
                            type="submit"
                            variant="primary"
                            loading={bulkTagsSaving}
                            disabledReason={tags.length ? undefined : 'Pick at least one tag'}
                            data-attr="analytics-bulk-tags-apply"
                        >
                            {adding ? 'Add tags' : 'Remove tags'}
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    )
}
