import { useState } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldError,
    FieldLabel,
    Input,
} from '@posthog/quill'

import { validateMetricName } from '../common'

const RENAME_INPUT_ID = 'data-catalog-metric-rename-input'

export interface QuillRenameMetricDialogProps {
    currentName: string
    isApproved: boolean
    onRename: (name: string) => void
    onCancel: () => void
}

export function QuillRenameMetricDialog({
    currentName,
    isApproved,
    onRename,
    onCancel,
}: QuillRenameMetricDialogProps): JSX.Element {
    const [name, setName] = useState(currentName)
    const [submitted, setSubmitted] = useState(false)
    const error = submitted ? validateMetricName(name) : undefined

    const submit = (): void => {
        setSubmitted(true)
        if (validateMetricName(name)) {
            return
        }
        onRename(name)
    }

    return (
        <Dialog open onOpenChange={(nextOpen: boolean) => !nextOpen && onCancel()}>
            <DialogContent>
                <form
                    className="contents"
                    onSubmit={(event) => {
                        event.preventDefault()
                        submit()
                    }}
                >
                    <DialogHeader>
                        <DialogTitle>Rename metric</DialogTitle>
                        <DialogDescription>
                            Anything that references this metric by name, like saved SQL queries, API calls, or links,
                            will stop working until it is updated. The old name becomes available for a new metric.
                            {isApproved &&
                                ' Renaming also sets the metric back to proposed, so it needs approving again.'}
                        </DialogDescription>
                    </DialogHeader>
                    <DialogBody>
                        <Field data-invalid={error ? true : undefined}>
                            <FieldLabel htmlFor={RENAME_INPUT_ID}>SQL name</FieldLabel>
                            <Input
                                id={RENAME_INPUT_ID}
                                value={name}
                                onChange={(event) => setName(event.target.value)}
                                aria-invalid={!!error}
                                data-attr="data-catalog-metric-rename-input"
                                autoFocus
                            />
                            {error && <FieldError>{error}</FieldError>}
                        </Field>
                    </DialogBody>
                    <DialogFooter>
                        <Button variant="outline" onClick={onCancel}>
                            Cancel
                        </Button>
                        <Button variant="primary" type="submit">
                            Rename
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    )
}
