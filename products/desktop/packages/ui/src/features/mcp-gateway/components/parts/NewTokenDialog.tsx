import { Check, Copy } from "@phosphor-icons/react";
import type { McpServiceAccountWithToken } from "@posthog/api-client/posthog-client";
import {
  Button,
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Text,
} from "@posthog/quill";
import { useState } from "react";

/** Shows a freshly-issued gateway token exactly once (creation or rotation). */
/** Not wired to a caller yet. The @public tag stops knip from reporting it. */
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
    <Dialog
      open={!!account}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <DialogContent className="sm:max-w-[440px]">
        <DialogHeader>
          <DialogTitle>
            Gateway token for {account?.name ?? "agent"}
          </DialogTitle>
        </DialogHeader>
        <DialogBody viewportClassName="flex flex-col gap-3">
          <div className="rounded-md border border-(--amber-6) bg-(--amber-2) px-3 py-2 text-(--amber-12)">
            <Text size="sm">
              Copy this token now — it's shown only once. The agent
              authenticates with it as a bearer token.
            </Text>
          </div>
          <div className="flex items-center gap-2 rounded border border-gray-5 bg-gray-2 px-3 py-2">
            <Text
              render={<span />}
              className="min-w-0 flex-1 break-all font-mono text-[12.5px]"
            >
              {account?.token}
            </Text>
            <Button
              type="button"
              variant="default"
              size="icon-xs"
              title="Copy token"
              onClick={() => void copy()}
            >
              {copied ? <Check /> : <Copy />}
            </Button>
          </div>
        </DialogBody>
        <DialogFooter>
          <DialogClose render={<Button variant="primary" />}>Done</DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
