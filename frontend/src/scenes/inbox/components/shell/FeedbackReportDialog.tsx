import { IconThumbsDown, IconThumbsUp } from '@posthog/icons'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { InboxReportFeedbackSentiment } from '../../inboxAnalytics'

/** Generous cap — feedback notes can be a paragraph or two of detail about a report or its PR. */
const FEEDBACK_NOTE_MAX_LENGTH = 10000

export interface FeedbackReportDialogResult {
    sentiment: InboxReportFeedbackSentiment
    note: string
}

interface OpenFeedbackReportDialogParams {
    /** Report title for the dialog copy. */
    reportTitle?: string | null
    /** Called with the chosen sentiment + note once the user submits. */
    onConfirm: (result: FeedbackReportDialogResult) => void | Promise<void>
}

const SENTIMENT_RADIO_OPTIONS: LemonRadioOption<InboxReportFeedbackSentiment>[] = [
    {
        value: 'positive',
        label: (
            <span className="inline-flex items-center gap-1.5">
                <IconThumbsUp className="shrink-0 text-success" />
                Helpful
            </span>
        ),
    },
    {
        value: 'negative',
        label: (
            <span className="inline-flex items-center gap-1.5">
                <IconThumbsDown className="shrink-0 text-danger" />
                Not helpful
            </span>
        ),
    },
]

/**
 * Opens the report feedback dialog: pick a thumbs sentiment plus an optional note, then submit.
 * Feedback-only — the report stays in the inbox (unlike {@link openDismissReportDialog}). The
 * caller wires `onConfirm` to fire the `Inbox report feedback` analytics event.
 */
export function openFeedbackReportDialog({ reportTitle, onConfirm }: OpenFeedbackReportDialogParams): void {
    LemonDialog.openForm({
        title: `Feedback on "${reportTitle?.trim() ? reportTitle : 'Untitled report'}"`,
        description:
            'Tell us how useful this report was. Your feedback helps the agent improve – it does not archive the report.',
        maxWidth: '30rem',
        initialValues: { sentiment: null as InboxReportFeedbackSentiment | null, note: '' },
        content: (
            <div className="flex flex-col gap-3">
                <LemonField name="sentiment" label="How useful was this?">
                    {({ value, onChange }) => (
                        <LemonRadio value={value} onChange={onChange} options={SENTIMENT_RADIO_OPTIONS} />
                    )}
                </LemonField>
                <LemonField name="note" label="Anything to add?" info="Optional – helps the agent learn">
                    <LemonTextArea
                        placeholder="Optional: what was useful or off?"
                        maxLength={FEEDBACK_NOTE_MAX_LENGTH}
                        rows={4}
                        // Keep Enter for newlines – without this it bubbles to the dialog's submit-on-Enter handler.
                        stopPropagation
                    />
                </LemonField>
            </div>
        ),
        errors: {
            sentiment: (sentiment) => (!sentiment ? "You haven't picked a rating" : undefined),
        },
        primaryButtonProps: { children: 'Send feedback' },
        shouldAwaitSubmit: true,
        onSubmit: async ({ sentiment, note }) => {
            if (!sentiment) {
                return
            }
            await onConfirm({ sentiment, note: (note ?? '').trim() })
        },
    })
}
