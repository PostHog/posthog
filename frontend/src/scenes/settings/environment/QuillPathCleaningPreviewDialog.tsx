import { useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Skeleton,
    Text,
} from '@posthog/quill'

import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { pathCleaningSuggestionsLogic } from './pathCleaningSuggestionsLogic'

export function QuillPathCleaningPreviewDialog({
    suggestionId,
    restrictedReason,
}: {
    suggestionId: string
    restrictedReason: string | null
}): JSX.Element {
    const { previewOpen, preview, previewLoading, applying } = useValues(pathCleaningSuggestionsLogic)
    const { closePreview, applySuggestion } = useActions(pathCleaningSuggestionsLogic)

    return (
        <Dialog open={previewOpen} onOpenChange={(open: boolean) => !open && closePreview()}>
            <DialogContent size="wide">
                <DialogHeader>
                    <DialogTitle>Preview on your real paths</DialogTitle>
                    <DialogDescription>
                        Your most-viewed paths from the last 30 days, with all suggested rules applied in order. Nothing
                        changes until you apply.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    {previewLoading || !preview ? (
                        <div className="flex flex-col gap-1">
                            <Skeleton className="h-8 w-full" />
                            <Skeleton className="h-8 w-full" />
                            <Skeleton className="h-8 w-full" />
                        </div>
                    ) : (
                        <div className="flex flex-col gap-2">
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                These rules group <strong>{preview.changed_path_count}</strong> of your top{' '}
                                <strong>{preview.sampled_path_count}</strong> paths
                                {preview.changed_path_count > preview.examples.length
                                    ? `, showing the first ${preview.examples.length}`
                                    : ''}
                                .
                            </Text>
                            <div className="flex flex-col gap-1">
                                {preview.examples.map((example) => (
                                    <div
                                        key={example.before}
                                        className="flex flex-wrap items-center gap-2 rounded-md border border-border p-2 font-mono text-xs"
                                    >
                                        <code>{example.before}</code>
                                        <IconArrowRight />
                                        <code className="font-semibold">{example.after}</code>
                                        <span className="ms-auto font-sans text-muted-foreground">
                                            {humanFriendlyLargeNumber(example.views)} views
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={closePreview}>
                        Close
                    </Button>
                    <Button
                        variant="primary"
                        onClick={() => applySuggestion(suggestionId)}
                        disabledReason={restrictedReason}
                        loading={applying}
                    >
                        Apply all
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
