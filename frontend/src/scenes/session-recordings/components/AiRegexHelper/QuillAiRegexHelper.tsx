import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { IconCopy, IconPlus } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldLabel,
    Heading,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    Textarea,
} from '@posthog/quill'

import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { aiRegexHelperLogic } from './aiRegexHelperLogic'

export function QuillAiRegexHelper({
    disabledReason,
    onApply,
}: {
    disabledReason: string | null
    onApply: () => void
}): JSX.Element {
    const { isOpen, input, generatedRegex, error, isLoading } = useValues(aiRegexHelperLogic)
    const { setInput, handleGenerateRegex, onClose, handleCopyToClipboard } = useActions(aiRegexHelperLogic)
    const inputId = useId()

    const generateButton = (
        <AIConsentPopoverWrapper>
            <Button
                data-attr="ai-regex-generate"
                variant={generatedRegex ? 'outline' : 'primary'}
                onClick={handleGenerateRegex}
                disabledReason={disabledReason}
                loading={isLoading}
            >
                {generatedRegex ? 'Regenerate' : 'Generate Regex'}
            </Button>
        </AIConsentPopoverWrapper>
    )

    return (
        <Dialog
            open={isOpen}
            onOpenChange={(open: boolean) => {
                if (!open) {
                    onClose()
                }
            }}
        >
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Max AI Regex Helper</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-4">
                        <Field>
                            <FieldLabel htmlFor={inputId}>Explain your regex in natural language:</FieldLabel>
                            <Textarea
                                id={inputId}
                                placeholder="I want a regex that covers all urls that include 'app.posthog.com/auth/*'"
                                rows={2}
                                value={input}
                                onChange={(event) => setInput(event.target.value)}
                            />
                        </Field>

                        {generatedRegex ? (
                            <div className="flex flex-col gap-2">
                                <Heading size="sm" render={<h3 className="m-0" />}>
                                    Your regex is:
                                </Heading>
                                <Item tone="info" size="sm">
                                    <ItemContent>
                                        <ItemDescription>
                                            <code translate="no" className="break-all">
                                                {generatedRegex}
                                            </code>
                                        </ItemDescription>
                                    </ItemContent>
                                    <ItemActions>
                                        <Button
                                            data-attr="ai-regex-copy"
                                            variant="outline"
                                            size="icon"
                                            onClick={handleCopyToClipboard}
                                            tooltip="Copy to clipboard"
                                            aria-label="Copy to clipboard"
                                        >
                                            <IconCopy />
                                        </Button>
                                    </ItemActions>
                                </Item>
                                <div className="flex justify-end">{generateButton}</div>
                            </div>
                        ) : null}

                        {error ? (
                            <Item tone="destructive" size="sm">
                                <ItemContent>
                                    <ItemDescription>{error}</ItemDescription>
                                </ItemContent>
                            </Item>
                        ) : null}
                    </div>
                </DialogBody>
                <DialogFooter>
                    <Button data-attr="ai-regex-close" variant="outline" onClick={onClose}>
                        Close
                    </Button>
                    {generatedRegex ? (
                        <Button data-attr="ai-regex-apply" variant="primary" onClick={onApply}>
                            <IconPlus />
                            Apply
                        </Button>
                    ) : (
                        generateButton
                    )}
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
