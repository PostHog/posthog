import type {
  SignalReport,
  SignalReportRefundReason,
} from "@posthog/shared/types";
import { Button } from "@posthog/ui/primitives/Button";
import { Dialog, Flex, RadioGroup, Text, TextArea } from "@radix-ui/themes";
import { useState } from "react";

const REFUND_REASON_OPTIONS: {
  value: SignalReportRefundReason;
  label: string;
}[] = [
  {
    value: "pr_incorrect",
    label: "The PR doesn't fix what the report describes",
  },
  { value: "pr_not_useful", label: "The PR works but is not useful to me" },
  { value: "duplicate", label: "Duplicate of work already covered" },
  { value: "other", label: "Something else…" },
];

export interface RefundReportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  report: SignalReport;
  isSubmitting: boolean;
  onConfirm: (result: {
    reason: SignalReportRefundReason;
    note: string;
  }) => void;
}

export function RefundReportDialog({
  open,
  onOpenChange,
  report,
  isSubmitting,
  onConfirm,
}: RefundReportDialogProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Content
        maxWidth="480px"
        onPointerDownOutside={() => {
          if (!isSubmitting) onOpenChange(false);
        }}
        onEscapeKeyDown={() => {
          if (!isSubmitting) onOpenChange(false);
        }}
      >
        <RefundReportDialogBody
          report={report}
          isSubmitting={isSubmitting}
          onConfirm={onConfirm}
        />
      </Dialog.Content>
    </Dialog.Root>
  );
}

function RefundReportDialogBody({
  report,
  isSubmitting,
  onConfirm,
}: Omit<RefundReportDialogProps, "open" | "onOpenChange">) {
  const [reason, setReason] = useState<SignalReportRefundReason | null>(null);
  const [note, setNote] = useState("");

  const title = report.title?.trim() ? report.title : "Untitled report";

  return (
    <>
      <Dialog.Title>
        <Text className="text-balance font-bold text-lg">
          Refund the PR for "{title}"?
        </Text>
      </Dialog.Title>
      <Dialog.Description className="text-gray-10 text-sm">
        You won't pay for this PR and it won't count toward your included PRs.
        The report is archived as part of the refund and can't be restored.
      </Dialog.Description>

      <Flex direction="column" gap="4" mt="4">
        <RadioGroup.Root
          size="1"
          value={reason ?? ""}
          onValueChange={(value) =>
            setReason(value as SignalReportRefundReason)
          }
        >
          <Flex direction="column" gap="2">
            {REFUND_REASON_OPTIONS.map((option) => (
              <Text key={option.value} as="label" size="2">
                <Flex gap="2" align="center">
                  <RadioGroup.Item value={option.value} />
                  {option.label}
                </Flex>
              </Text>
            ))}
          </Flex>
        </RadioGroup.Root>

        <TextArea
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Optional: helps us review refunds"
          size="1"
          rows={3}
          maxLength={4000}
          disabled={isSubmitting}
        />
      </Flex>

      <Flex gap="3" mt="4" justify="end">
        <Dialog.Close>
          <Button variant="soft" color="gray">
            Cancel
          </Button>
        </Dialog.Close>
        <Button
          variant="solid"
          disabled={!reason || isSubmitting}
          disabledReason={!reason ? "you haven't picked a reason" : null}
          onClick={() => reason && onConfirm({ reason, note: note.trim() })}
          loading={isSubmitting}
        >
          Refund
        </Button>
      </Flex>
    </>
  );
}
