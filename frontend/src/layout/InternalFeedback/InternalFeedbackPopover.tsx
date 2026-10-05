import { useActions, useValues } from 'kea'

import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { internalFeedbackLogic } from './internalFeedbackLogic'

const POPOVER_WIDTH = 320
// Room the popover needs below the element before it flips into view from the bottom edge.
const POPOVER_HEIGHT = 260

export function InternalFeedbackPopover(): JSX.Element | null {
    const { target, selectedElementRect, comment, isSubmitting } = useValues(internalFeedbackLogic)
    const { setComment, submitFeedback, clearSelection } = useActions(internalFeedbackLogic)

    if (!target) {
        return null
    }

    let top = 80
    let left = 16
    if (selectedElementRect) {
        top = Math.max(
            8,
            Math.min(selectedElementRect.top + selectedElementRect.height + 8, window.innerHeight - POPOVER_HEIGHT)
        )
        left = Math.min(Math.max(selectedElementRect.left, 8), window.innerWidth - POPOVER_WIDTH - 8)
    }

    return (
        <div
            className="fixed z-[2147483647] pointer-events-auto flex flex-col gap-2 p-3 rounded-lg border border-primary bg-surface-primary shadow-lg w-80 max-w-[calc(100vw-1rem)]"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ top, left }}
        >
            <div className="font-semibold">Send feedback to devs</div>
            <code className="text-xs text-secondary truncate" title={target.identifier}>
                {target.identifier}
            </code>
            <LemonTextArea
                placeholder="What should change here? (⌘↵ to save)"
                value={comment}
                onChange={setComment}
                onPressCmdEnter={() => comment.trim() && !isSubmitting && submitFeedback()}
                minRows={3}
                autoFocus
                data-attr="internal-feedback-comment"
            />
            <div className="flex gap-2">
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => clearSelection()}
                    className="flex-1"
                    center
                    data-attr="internal-feedback-cancel"
                >
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={() => submitFeedback()}
                    loading={isSubmitting}
                    disabledReason={!comment.trim() ? 'Write some feedback first' : undefined}
                    className="flex-1"
                    center
                    data-attr="internal-feedback-save"
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
