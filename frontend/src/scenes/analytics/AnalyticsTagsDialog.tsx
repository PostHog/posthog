import { useActions, useValues } from 'kea'
import { useId } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@posthog/quill'

import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'
import { useTagPages } from 'lib/components/useTagPages'

import { analyticsTagsLogic } from './analyticsTagsLogic'

/** Edits one list row's tags, opened from the row's tag menu. */
export function AnalyticsTagsDialog(): JSX.Element {
    const { target, draftTags, saving, hasChanges } = useValues(analyticsTagsLogic)
    const { closeTagEditor, setDraftTags, saveTags } = useActions(analyticsTagsLogic)
    const tagPages = useTagPages(useId())

    return (
        <Dialog
            open={!!target}
            // Closing mid-save would let another row's editor open, which the finished save would then close.
            onOpenChange={(open: boolean) => !open && !saving && closeTagEditor()}
        >
            <DialogContent data-attr="analytics-tags-dialog">
                <DialogHeader>
                    <DialogTitle>Manage tags</DialogTitle>
                    <DialogDescription>{target ? `Tags on "${target.name}".` : ''}</DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <TagsCombobox
                        value={draftTags}
                        onChange={setDraftTags}
                        options={tagPages.tags.map(({ tag }) => tag).filter((tag) => !draftTags.includes(tag))}
                        loading={tagPages.awaitingFirstPage || tagPages.pageLoading}
                        onOpen={() => tagPages.setOpen(true)}
                        onClose={() => tagPages.setOpen(false)}
                        onInputChange={tagPages.setSearch}
                        error={tagPages.error ? "Couldn't load tags." : undefined}
                        onRetry={tagPages.retry}
                        onScrollEnd={tagPages.loadMore}
                        loadingMore={tagPages.pageLoading && tagPages.tags.length > 0}
                        placeholder="Add tags..."
                        allowCustomValues
                        customValueNoun="tag"
                        autoFocus
                        disabled={saving}
                        dataAttr="analytics-tags-input"
                    />
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={() => closeTagEditor()} disabled={saving}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={() => saveTags()}
                        loading={saving}
                        disabled={!hasChanges}
                        data-attr="analytics-tags-save"
                    >
                        Save
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
