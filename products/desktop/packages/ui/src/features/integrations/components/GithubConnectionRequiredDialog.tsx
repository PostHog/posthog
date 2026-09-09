import { Check, Copy } from "@phosphor-icons/react";
import {
  GITHUB_ADMIN_ACCESS_REQUEST,
  GITHUB_CLOUD_TASK_CONNECTION_REQUIRED_MESSAGE,
  GITHUB_CODE_CONTEXT_MESSAGE,
} from "@posthog/core/integrations/connectErrors";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@posthog/quill";
import { useCallback, useState } from "react";

interface GithubConnectionRequiredDialogProps {
  open: boolean;
  isConnecting: boolean;
  connectionMessage?: string;
  requirementMessage?: string;
  approvalPending?: boolean;
  canRunLocally: boolean;
  onOpenChange: (open: boolean) => void;
  onConnect: () => void;
  onRunLocally: () => void;
}

export function GithubConnectionRequiredDialog({
  open,
  isConnecting,
  connectionMessage,
  requirementMessage = GITHUB_CLOUD_TASK_CONNECTION_REQUIRED_MESSAGE,
  approvalPending = false,
  canRunLocally,
  onOpenChange,
  onConnect,
  onRunLocally,
}: GithubConnectionRequiredDialogProps) {
  const [showWhy, setShowWhy] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      if (!nextOpen) {
        setShowWhy(false);
        setCopied(false);
      }
      onOpenChange(nextOpen);
    },
    [onOpenChange],
  );

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(GITHUB_ADMIN_ACCESS_REQUEST);
    setCopied(true);
  }, []);

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Connect GitHub</DialogTitle>
          <DialogDescription>{requirementMessage}</DialogDescription>
        </DialogHeader>

        {connectionMessage ? (
          <p
            className={
              approvalPending
                ? "text-(--gray-11) text-sm"
                : "text-(--red-11) text-sm"
            }
          >
            {connectionMessage}
          </p>
        ) : null}

        {showWhy || approvalPending ? (
          <div className="flex flex-col gap-2 rounded-(--radius-2) border border-(--gray-6) bg-(--gray-2) p-3">
            <p className="m-0 text-sm">{GITHUB_CODE_CONTEXT_MESSAGE}</p>
            <div className="flex items-start gap-2 rounded-(--radius-2) bg-(--gray-3) p-2">
              <p className="m-0 min-w-0 flex-1 select-text text-sm">
                {GITHUB_ADMIN_ACCESS_REQUEST}
              </p>
              <Button
                type="button"
                variant="outline"
                size="icon-sm"
                aria-label="Copy access request"
                data-attr="copy-github-access-request"
                onClick={() => void handleCopy()}
              >
                {copied ? <Check size={14} /> : <Copy size={14} />}
              </Button>
            </div>
          </div>
        ) : null}

        {canRunLocally ? (
          <p className="m-0 text-(--gray-11) text-sm">
            A local run can use this folder now, but its result can become
            stale. GitHub is required for ongoing background work.
          </p>
        ) : null}

        <DialogFooter className="flex-wrap">
          {canRunLocally ? (
            <Button
              type="button"
              variant="outline"
              data-attr="run-with-local-code-snapshot"
              onClick={onRunLocally}
            >
              Run with local code snapshot
            </Button>
          ) : null}
          <Button
            type="button"
            variant="link-muted"
            data-attr="explain-github-code-context"
            onClick={() => setShowWhy((shown) => !shown)}
          >
            Why do I need this?
          </Button>
          <Button
            type="button"
            variant="primary"
            loading={isConnecting}
            disabled={isConnecting}
            data-attr="connect-github-for-code-context"
            onClick={onConnect}
          >
            Connect GitHub
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
