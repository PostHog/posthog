import { KeyIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/ui/primitives/Button";
import { Flex, Text, TextField } from "@radix-ui/themes";
import { type KeyboardEvent, useState } from "react";
import type { PendingSecret } from "./agentBuilderStore";

/**
 * Inline punch-out for the agent builder's `set_secret` tool. The agent never sees
 * the raw value: the form PUTs it straight to the env-keys API and only the
 * `{ key, action }` outcome is posted back to wake the session. Shown above the
 * dock composer while a secret is pending.
 */
export function AgentBuilderSecretForm({
  pending,
  busy,
  onSubmit,
  onCancel,
}: {
  pending: PendingSecret;
  busy: boolean;
  onSubmit: (value: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState("");
  const action = pending.mode === "rotate" ? "Rotate" : "Set";

  function submit() {
    const trimmed = value.trim();
    if (!trimmed || busy) return;
    onSubmit(trimmed);
  }
  function onKeyDown(e: KeyboardEvent) {
    if (e.key === "Enter") {
      e.preventDefault();
      submit();
    }
  }

  return (
    <Flex
      direction="column"
      gap="2"
      className="shrink-0 border-(--gray-5) border-t bg-(--gray-2) px-4 py-3"
    >
      <Flex align="center" gap="2">
        <KeyIcon size={14} className="shrink-0 text-(--accent-9)" />
        <Text className="font-medium text-[12.5px] text-gray-12">
          {action} secret{" "}
          <span className="font-mono text-(--accent-11)">{pending.secret}</span>
        </Text>
      </Flex>
      {pending.purpose ? (
        <Text className="text-[11.5px] text-gray-10 leading-snug">
          {pending.purpose}
        </Text>
      ) : null}
      <Text className="text-[11px] text-gray-9 leading-snug">
        The value is sent straight to your agent's secrets — the agent builder
        never sees it.
      </Text>
      <Flex align="center" gap="2">
        <TextField.Root
          type="password"
          autoComplete="off"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={`Value for ${pending.secret}`}
          className="flex-1 text-[13px]"
          autoFocus
        />
        <Button size="1" onClick={submit} disabled={!value.trim() || busy}>
          {busy ? "Saving…" : action}
        </Button>
        <Button
          variant="soft"
          color="gray"
          size="1"
          onClick={onCancel}
          disabled={busy}
        >
          Cancel
        </Button>
      </Flex>
    </Flex>
  );
}
