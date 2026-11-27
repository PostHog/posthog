import { useActions, useValues } from 'kea'

import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    DialogBody,
    Field,
    FieldError,
    FieldLabel,
    Item,
    ItemContent,
    Separator,
    Spinner,
    Text,
} from '@posthog/quill'

import { TAG_REFERENCE_WARNING, tagsLogic } from './tagsLogic'

export function MergeTagModalQuill(): JSX.Element | null {
    const {
        tagToMerge,
        target,
        destinations,
        destinationPage,
        destinationPageLoading,
        destinationError,
        preview,
        previewLoading,
        previewError,
        canSubmitMerge,
        mutationLoading,
        mutationError,
    } = useValues(tagsLogic)
    const { closeModals, setTarget, setDestinationSearch, retryDestinations, loadMoreDestinations, submitMerge } =
        useActions(tagsLogic)
    if (!tagToMerge) {
        return null
    }
    const options =
        target && !destinations.some((tag) => tag.id === target.id) ? [target, ...destinations] : destinations
    return (
        <AlertDialog
            open
            onOpenChange={(open) => {
                if (!open && !mutationLoading) {
                    closeModals()
                }
            }}
        >
            <AlertDialogContent className="grid grid-cols-1 ph-no-capture">
                <AlertDialogHeader>
                    <AlertDialogTitle className="wrap-anywhere">{`Merge tag "${tagToMerge.name}"`}</AlertDialogTitle>
                    <AlertDialogDescription>
                        Move this tag's assignments into an existing tag, then remove this tag. This cannot be undone.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <DialogBody className="min-w-0" viewportClassName="flex flex-col gap-4">
                    <Field>
                        <FieldLabel htmlFor="merge-tag-destination">Destination tag</FieldLabel>
                        <Combobox<string>
                            items={options.map((tag) => tag.id)}
                            value={target?.id ?? null}
                            onValueChange={(id) => setTarget(options.find((tag) => tag.id === id) ?? null)}
                            onInputValueChange={setDestinationSearch}
                            itemToStringLabel={(id) => options.find((tag) => tag.id === id)?.name ?? id}
                            filter={null}
                            disabled={mutationLoading}
                        >
                            <ComboboxInput
                                id="merge-tag-destination"
                                placeholder="Search existing tags"
                                data-attr="tag-management-merge-destination"
                            />
                            <ComboboxContent className="ph-no-capture">
                                <ComboboxEmpty>
                                    {destinationPageLoading ? 'Loading tags...' : 'No matching tags'}
                                </ComboboxEmpty>
                                <ComboboxList>
                                    {(id: string) => (
                                        <ComboboxItem key={id} value={id}>
                                            {options.find((tag) => tag.id === id)?.name}
                                        </ComboboxItem>
                                    )}
                                </ComboboxList>
                            </ComboboxContent>
                        </Combobox>
                        {destinationError && <FieldError>{destinationError}</FieldError>}
                        {destinationError && (
                            <Button variant="outline" onClick={retryDestinations}>
                                Try again
                            </Button>
                        )}
                    </Field>
                    {destinationPage?.next && !destinationError && (
                        <Button variant="default" onClick={loadMoreDestinations} loading={destinationPageLoading}>
                            Load more tags
                        </Button>
                    )}
                    {previewLoading ? (
                        <Spinner />
                    ) : previewError ? (
                        <FieldError>{previewError}</FieldError>
                    ) : preview && target && preview.tag.id === target.id ? (
                        <section className="flex flex-col gap-2" aria-label="Merge summary">
                            {[
                                { name: tagToMerge.name, count: preview.source_count },
                                { name: target.name, count: preview.target_count },
                            ].map(({ name, count }) => (
                                <div key={name} className="flex items-baseline justify-between gap-4">
                                    <Text size="xs" className="m-0 min-w-0 wrap-anywhere">
                                        <code className="whitespace-normal">{name}</code>
                                        <span> assignments</span>
                                    </Text>
                                    <Text size="xs" className="m-0 shrink-0 tabular-nums">
                                        {count.toLocaleString()}
                                    </Text>
                                </div>
                            ))}
                            <div className="flex items-baseline justify-between gap-4">
                                <Text size="xs" className="m-0">
                                    Overlaps
                                </Text>
                                <Text size="xs" className="m-0 shrink-0 tabular-nums">
                                    {`- ${preview.overlap_count.toLocaleString()}`}
                                </Text>
                            </div>
                            <Separator />
                            <div className="flex items-baseline justify-between gap-4">
                                <Text size="xs" weight="semibold" className="m-0">
                                    Assignments after merge
                                </Text>
                                <Text size="xs" weight="semibold" className="m-0 shrink-0 tabular-nums">
                                    {preview.result_count.toLocaleString()}
                                </Text>
                            </div>
                        </section>
                    ) : null}
                    <Item tone="warning">
                        <ItemContent>{TAG_REFERENCE_WARNING}</ItemContent>
                    </Item>
                    {mutationError && <FieldError>{mutationError}</FieldError>}
                </DialogBody>
                <AlertDialogFooter>
                    <Button
                        variant="outline"
                        onClick={closeModals}
                        disabledReason={mutationLoading ? 'Wait for the merge to finish.' : undefined}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="destructive-outline"
                        onClick={submitMerge}
                        loading={mutationLoading}
                        disabledReason={!canSubmitMerge ? 'Choose a destination and wait for the preview.' : undefined}
                        data-attr="tag-management-merge-confirm"
                    >
                        Merge tags
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
