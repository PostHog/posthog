import { Check, Copy } from "@phosphor-icons/react";
import type { McpServiceAccountWithToken } from "@posthog/api-client/posthog-client";
import {
  Button,
  Callout,
  Dialog,
  Flex,
  IconButton,
  Text,
} from "@radix-ui/themes";
import { useState } from "react";

/** Shows a freshly-issued gateway token exactly once (creation or rotation). */
export function NewTokenDialog({
  account,
  onClose,
}: {
  account: McpServiceAccountWithToken | null;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    if (!account) return;
    await navigator.clipboard.writeText(account.token);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <Dialog.Root
      open={!!account}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <Dialog.Content maxWidth="440px">
        <Dialog.Title>
          Gateway token for {account?.name ?? "agent"}
        </Dialog.Title>
        <Flex direction="column" gap="3">
          <Callout.Root color="amber" size="1">
            <Callout.Text>
              Copy this token now — it's shown only once. The agent
              authenticates with it as a bearer token.
            </Callout.Text>
          </Callout.Root>
          <Flex
            align="center"
            gap="2"
            className="rounded border border-gray-5 bg-gray-2 px-3 py-2"
          >
            <Text className="min-w-0 flex-1 break-all font-mono text-[12.5px]">
              {account?.token}
            </Text>
            <IconButton
              variant="ghost"
              color="gray"
              size="1"
              title="Copy token"
              onClick={copy}
            >
              {copied ? <Check size={13} /> : <Copy size={13} />}
            </IconButton>
          </Flex>
        </Flex>
        <Flex justify="end" mt="4">
          <Button variant="solid" onClick={onClose}>
            Done
          </Button>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
