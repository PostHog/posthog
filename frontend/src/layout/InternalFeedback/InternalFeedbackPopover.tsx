import { useActions, useValues } from 'kea'

import {
    Button,
    Card,
    CardContent,
    CardDescription,
    CardFooter,
    CardHeader,
    CardTitle,
    Field,
    FieldError,
    FieldLabel,
    Textarea,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { INTERNAL_FEEDBACK_IGNORE_ATTR } from './captureFeedbackScreenshot'
import { internalFeedbackLogic } from './internalFeedbackLogic'

const POPOVER_WIDTH = 320
// Room the card needs below the element before it moves up to stay in view.
const POPOVER_HEIGHT = 300
const COMMENT_INPUT_ID = 'internal-feedback-comment'

export function InternalFeedbackPopover(): JSX.Element | null {
    const { target, selectedElementRect, comment, isSubmitting, submitError } = useValues(internalFeedbackLogic)
    const { setComment, submitFeedback, clearSelection } = useActions(internalFeedbackLogic)

    if (!target) {
        return null
    }

    // Whole-page feedback has no element to sit next to, so the card centers in the viewport.
    let position: React.CSSProperties | undefined
    if (selectedElementRect) {
        position = {
            top: Math.max(
                8,
                Math.min(selectedElementRect.top + selectedElementRect.height + 8, window.innerHeight - POPOVER_HEIGHT)
            ),
            left: Math.min(Math.max(selectedElementRect.left, 8), window.innerWidth - POPOVER_WIDTH - 8),
        }
    }
    const canSave = !!comment.trim()

    return (
        <Card
            size="sm"
            data-quill
            {...{ [INTERNAL_FEEDBACK_IGNORE_ATTR]: '' }}
            // Same top layer as the bar, so an open modal or menu never covers the card.
            className={cn(
                'fixed z-[2147483647] pointer-events-auto w-80 shadow-md',
                !position && 'top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={position}
        >
            <CardHeader>
                <CardTitle>Send feedback to devs</CardTitle>
                {!target.element && <CardDescription>About this whole page</CardDescription>}
            </CardHeader>
            <CardContent>
                <Field>
                    <FieldLabel htmlFor={COMMENT_INPUT_ID}>What should change?</FieldLabel>
                    <Textarea
                        id={COMMENT_INPUT_ID}
                        placeholder="⌘↵ to save"
                        value={comment}
                        onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setComment(e.target.value)}
                        onKeyDown={(e: React.KeyboardEvent<HTMLTextAreaElement>) => {
                            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && canSave && !isSubmitting) {
                                e.preventDefault()
                                submitFeedback()
                            }
                        }}
                        rows={3}
                        // The textarea grows with its content, so cap it to keep Save inside the viewport.
                        className="max-h-48"
                        autoFocus
                        data-attr="internal-feedback-comment"
                    />
                    {submitError && <FieldError>{submitError}</FieldError>}
                </Field>
            </CardContent>
            <CardFooter className="justify-end gap-2">
                <Button variant="outline" onClick={() => clearSelection()} data-attr="internal-feedback-cancel">
                    Cancel
                </Button>
                <Tooltip disabled={canSave}>
                    <TooltipTrigger
                        render={
                            <Button
                                variant="primary"
                                loading={isSubmitting}
                                disabled={!canSave}
                                onClick={() => submitFeedback()}
                                data-attr="internal-feedback-save"
                            />
                        }
                    >
                        Save
                    </TooltipTrigger>
                    <TooltipContent>Write some feedback first</TooltipContent>
                </Tooltip>
            </CardFooter>
        </Card>
    )
}
