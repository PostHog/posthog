import { Button, Popover, PopoverContent } from '@posthog/quill'

import type { QuerySaveConfirmationProps } from './QuerySaveConfirmation'

export function QuillQuerySaveConfirmation({
    open,
    anchor,
    onClose,
    onRunLatest,
    onShowDiff,
    onSaveAnyway,
}: QuerySaveConfirmationProps): JSX.Element {
    return (
        <Popover
            open={open}
            onOpenChange={(open) => {
                if (!open) {
                    onClose()
                }
            }}
        >
            <PopoverContent
                anchor={anchor}
                side="bottom"
                align="end"
                className="w-96 max-w-[calc(100vw-2rem)]"
                aria-label="Save query without running"
            >
                <p>The query you’re saving has not been run successfully. Results may be from a different query.</p>
                <div className="flex flex-wrap justify-end gap-2">
                    <Button variant="outline" onClick={onRunLatest} data-attr="sql-editor-save-run-latest">
                        Run latest
                    </Button>
                    <Button variant="outline" onClick={onShowDiff} data-attr="sql-editor-save-show-diff">
                        Show diff
                    </Button>
                    <Button variant="primary" onClick={onSaveAnyway} data-attr="sql-editor-save-anyway">
                        Save anyway
                    </Button>
                </div>
            </PopoverContent>
        </Popover>
    )
}
