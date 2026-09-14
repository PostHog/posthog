import { Check, Copy } from "@phosphor-icons/react";
import type { McpServiceAccountWithToken } from "@posthog/api-client/posthog-client";
import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
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
      <DialogContent className="max-w-[440px]">
        <DialogHeader>
          <DialogTitle>
            Gateway token for {account?.name ?? "agent"}
          </DialogTitle>
        </DialogHeader>
        <DialogBody>
          <div className="flex flex-col gap-3">
            <p
              role="alert"
              className="rounded-md border border-amber-7 bg-amber-3 px-3 py-2 text-amber-12 text-sm"
            >
              Copy this token now — it's shown only once. The agent
              authenticates with it as a bearer token.
            </p>
            <div className="flex items-center gap-2 rounded border border-gray-5 bg-gray-2 px-3 py-2">
              <code className="min-w-0 flex-1 break-all text-[12.5px]">
                {account?.token}
              </code>
              <Button
                variant="link-muted"
                size="icon-xs"
                aria-label="Copy token"
                title="Copy token"
                onClick={copy}
              >
                {copied ? <Check size={13} /> : <Copy size={13} />}
              </Button>
            </div>
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="primary" onClick={onClose}>
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
