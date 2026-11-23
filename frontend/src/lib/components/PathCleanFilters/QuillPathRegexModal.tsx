import { useId } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldDescription,
    FieldLabel,
    Input,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

export function QuillPathRegexModal({
    isOpen,
    isNew,
    regex,
    alias,
    disabledReason,
    onRegexChange,
    onAliasChange,
    onSave,
    onClose,
    aiRegexHelper,
    aiRegexHelperOpen,
}: {
    isOpen: boolean
    isNew: boolean
    regex: string
    alias: string
    disabledReason: string | null
    onRegexChange: (regex: string) => void
    onAliasChange: (alias: string) => void
    onSave: () => void
    onClose: () => void
    /** The AI regex helper and its trigger, which the caller owns. */
    aiRegexHelper: React.ReactNode
    aiRegexHelperOpen: boolean
}): JSX.Element {
    const regexId = useId()
    const aliasId = useId()

    return (
        <Dialog
            open={isOpen}
            onOpenChange={(open: boolean) => {
                // The AI regex helper opens its own dialog on top, and working in it must not close this dialog.
                if (!open && !aiRegexHelperOpen) {
                    onClose()
                }
            }}
        >
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>{isNew ? 'Add Path Cleaning Rule' : 'Edit Path Cleaning Rule'}</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-4" data-attr="path-regex-modal-content">
                        <Field>
                            <FieldLabel htmlFor={regexId}>Regex</FieldLabel>
                            <Input
                                id={regexId}
                                className="font-mono"
                                value={regex}
                                onChange={(event) => onRegexChange(event.target.value)}
                            />
                            <FieldDescription>
                                Example: <code translate="no">/merchant/\d+/dashboard$</code> (no need to escape
                                slashes)
                            </FieldDescription>
                            <FieldDescription>
                                We use the{' '}
                                <Button
                                    variant="link"
                                    size="inline"
                                    nativeButton={false}
                                    render={
                                        <LinkPrimitive to="https://github.com/google/re2/wiki/Syntax" target="_blank" />
                                    }
                                >
                                    re2
                                </Button>{' '}
                                syntax.
                            </FieldDescription>
                        </Field>
                        <Field>
                            <FieldLabel htmlFor={aliasId}>Alias</FieldLabel>
                            <Input
                                id={aliasId}
                                className="font-mono"
                                value={alias}
                                onChange={(event) => onAliasChange(event.target.value)}
                            />
                            <FieldDescription>How the path will appear after path cleaning</FieldDescription>
                            <FieldDescription>
                                Example: <code translate="no">{'/merchant/<id>/dashboard'}</code>
                            </FieldDescription>
                            <FieldDescription>
                                To keep part of the original path, reference a capture group from the regex with{' '}
                                <code translate="no">{'\\1'}</code>, <code translate="no">{'\\2'}</code>, and so on. For
                                example, regex <code translate="no">{'/user/(\\d+)/profile'}</code> with alias{' '}
                                <code translate="no">{'/user/\\1'}</code> keeps the id. Capture groups slow queries
                                down, so use them when one rule can replace several near-identical ones.
                            </FieldDescription>
                        </Field>
                        <div>{aiRegexHelper}</div>
                    </div>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button variant="primary" onClick={onSave} disabledReason={disabledReason}>
                        Save
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
