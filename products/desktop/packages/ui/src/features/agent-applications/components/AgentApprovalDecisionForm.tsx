import { CheckIcon, XIcon } from "@phosphor-icons/react";
import type {
  AgentApprovalRequest,
  DecideApprovalRequest,
} from "@posthog/shared/agent-platform-types";
import { Button } from "@posthog/ui/primitives/Button";
import { Checkbox, Flex, Text, TextArea } from "@radix-ui/themes";
import { useState } from "react";

/**
 * Presentational approve/reject controls for a queued approval — proposed-args
 * editor (when allowed), reason note, error surface, and the two action
 * buttons. Owns its own UI state but takes the decision callback from the
 * caller, so both the full `AgentApprovalDetail` (Approvals tab + Fleet route)
 * and the inline `AgentChatPendingApprovalCard` (chat pane) can wrap
 * it with their own `useDecideAgentApproval` glue.
 */
export function AgentApprovalDecisionForm({
  approval,
  busy,
  error,
  onSubmit,
}: {
  approval: AgentApprovalRequest;
  busy: boolean;
  error: string | null;
  onSubmit: (body: DecideApprovalRequest) => void;
}) {
  const allowEdit = approval.approver_scope?.allow_edit === true;
  const [reason, setReason] = useState("");
  const [editMode, setEditMode] = useState(false);
  const [argsText, setArgsText] = useState(() =>
    JSON.stringify(approval.proposed_args, null, 2),
  );
  const [parseError, setParseError] = useState<string | null>(null);

  function submit(decision: "approve" | "reject") {
    const body: DecideApprovalRequest = { decision };
    if (reason.trim()) body.reason = reason.trim();
    if (decision === "approve" && allowEdit && editMode) {
      try {
        body.edited_args = JSON.parse(argsText);
      } catch (err) {
        setParseError(err instanceof Error ? err.message : "Invalid JSON");
        return;
      }
    }
    setParseError(null);
    onSubmit(body);
  }

  return (
    <Flex direction="column" gap="3" className="mt-4">
      {allowEdit ? (
        <Text as="label" className="w-fit text-[12px] text-gray-11">
          <Flex gap="2" align="center">
            <Checkbox
              size="1"
              checked={editMode}
              onCheckedChange={(c) => setEditMode(c === true)}
            />
            Approve with edits
          </Flex>
        </Text>
      ) : null}

      {allowEdit && editMode ? (
        <div>
          <TextArea
            value={argsText}
            onChange={(e) => setArgsText(e.target.value)}
            rows={8}
            className="text-[12px] [font-family:var(--font-mono)]"
            spellCheck={false}
          />
          {parseError ? (
            <Text className="mt-1 block text-(--red-11) text-[11px]">
              {parseError}
            </Text>
          ) : null}
        </div>
      ) : null}

      <TextArea
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="Reason (optional)"
        rows={2}
        className="text-[12px]"
      />

      {error ? (
        <Text className="text-(--red-11) text-[11px]">{error}</Text>
      ) : null}

      <Flex gap="2">
        <Button
          color="green"
          size="2"
          onClick={() => submit("approve")}
          disabled={busy}
          loading={busy}
        >
          <CheckIcon size={14} />
          Approve
        </Button>
        <Button
          color="red"
          variant="soft"
          size="2"
          onClick={() => submit("reject")}
          disabled={busy}
        >
          <XIcon size={14} />
          Reject
        </Button>
      </Flex>
    </Flex>
  );
}
