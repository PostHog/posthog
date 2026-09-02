import { ThumbsDownIcon, ThumbsUpIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import type { InboxReportFeedbackSentiment } from "@posthog/shared";
import type { SignalReport } from "@posthog/shared/types";
import {
  FEEDBACK_NOTE_MAX_LENGTH,
  useReportFeedbackTracker,
} from "@posthog/ui/features/inbox/hooks/useReportFeedbackTracker";
import { Flex, Text, TextArea } from "@radix-ui/themes";
import { useCallback, useState } from "react";

/**
 * Thumbs rating at the end of the report body, where the reader has just
 * finished reading. The rating submits on the first click, so there is no text
 * field to mistake for a dismissal reason. Only once a rating is recorded does
 * an optional note appear, so the note can never gate the rating and ignoring
 * it leaves the flow exactly as it was. Feedback is analytics-only: it never
 * changes the report's state.
 */
export function ReportFeedbackFooter({ report }: { report: SignalReport }) {
  const { rate, note } = useReportFeedbackTracker(report);

  const [sentiment, setSentiment] =
    useState<InboxReportFeedbackSentiment | null>(null);
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteDraft, setNoteDraft] = useState("");
  const [noteSent, setNoteSent] = useState(false);

  const isPositive = sentiment === "positive";
  const isNegative = sentiment === "negative";

  // Re-clicking the chosen thumb is a no-op rather than a second identical
  // feedback event; switching thumbs records the new sentiment.
  const chooseSentiment = useCallback(
    (next: InboxReportFeedbackSentiment) => {
      if (sentiment === next) return;
      setSentiment(next);
      rate(next);
    },
    [sentiment, rate],
  );

  const submitNote = useCallback(() => {
    const trimmed = noteDraft.trim();
    if (!trimmed || !sentiment) return;
    note(sentiment, trimmed);
    setNoteDraft("");
    setNoteOpen(false);
    setNoteSent(true);
  }, [noteDraft, sentiment, note]);

  return (
    <div className="flex flex-col gap-2 pt-1">
      <Flex align="center" gap="2" wrap="wrap" className="select-none">
        <Text size="1" color="gray">
          {sentiment ? "Thanks for the feedback" : "Was this report useful?"}
        </Text>
        <Flex align="center" gap="1">
          <Button
            type="button"
            variant={isPositive ? "primary" : "outline"}
            size="sm"
            aria-label="This report was useful"
            aria-pressed={isPositive}
            title="Yes, this was useful"
            onClick={() => chooseSentiment("positive")}
          >
            <ThumbsUpIcon size={12} weight={isPositive ? "fill" : "regular"} />
          </Button>
          <Button
            type="button"
            variant={isNegative ? "primary" : "outline"}
            size="sm"
            aria-label="This report was not useful"
            aria-pressed={isNegative}
            title="No, this wasn't useful"
            onClick={() => chooseSentiment("negative")}
          >
            <ThumbsDownIcon
              size={12}
              weight={isNegative ? "fill" : "regular"}
            />
          </Button>
        </Flex>
        {sentiment && !noteOpen && !noteSent && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setNoteOpen(true)}
          >
            Add a note
          </Button>
        )}
        {noteSent && (
          <Text size="1" color="gray">
            Note added
          </Text>
        )}
      </Flex>
      {noteOpen && (
        <Flex direction="column" align="start" gap="2" className="max-w-prose">
          <TextArea
            aria-label="Add a note about this report"
            autoFocus
            placeholder="What was useful or off?"
            resize="vertical"
            rows={3}
            size="2"
            maxLength={FEEDBACK_NOTE_MAX_LENGTH}
            value={noteDraft}
            onChange={(event) => setNoteDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                submitNote();
              }
            }}
            className="w-full"
          />
          <Button
            type="button"
            variant="primary"
            size="sm"
            disabled={noteDraft.trim().length === 0}
            onClick={submitNote}
          >
            Send
          </Button>
        </Flex>
      )}
    </div>
  );
}
