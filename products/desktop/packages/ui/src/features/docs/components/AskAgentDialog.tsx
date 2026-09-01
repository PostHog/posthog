import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Text,
  Textarea,
} from "@posthog/quill";
import { useEffect, useState } from "react";

/**
 * Asks the agent about the selected part of a doc.
 *
 * The answer arrives in a thread beside the page, not in the page.
 */
export function AskAgentDialog({
  open,
  onOpenChange,
  contextText,
  pending,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  contextText: string;
  pending: boolean;
  onConfirm: (question: string) => void;
}) {
  const [question, setQuestion] = useState("");
  useEffect(() => {
    if (open) setQuestion("");
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Ask the agent</DialogTitle>
          <DialogDescription>
            The agent answers in a thread beside this page. It never writes into
            the page. You decide what goes in.
          </DialogDescription>
        </DialogHeader>

        <DialogBody viewportClassName="flex flex-col gap-3">
          {contextText ? (
            <Text size="sm" className="truncate text-(--gray-11) italic">
              “{contextText}”
            </Text>
          ) : null}
          <Textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="What do you want the agent to look into?"
            rows={4}
            autoFocus
          />
        </DialogBody>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={pending}
            disabled={pending || question.trim().length === 0}
            onClick={() => onConfirm(question.trim())}
          >
            Ask
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
