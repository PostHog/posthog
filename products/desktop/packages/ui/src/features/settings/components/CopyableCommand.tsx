import { Check, Copy } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { type ReactElement, useCallback, useState } from "react";

export function CopyableCommand({
  command,
}: {
  command: string;
}): ReactElement {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(command);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [command]);

  return (
    <span className="inline-flex shrink-0 items-center gap-1 rounded border border-border bg-muted py-0.5 pr-0.5 pl-2">
      <code className="font-mono text-muted-foreground text-xs">{command}</code>
      <Tooltip content={copied ? "Copied!" : "Copy"}>
        <Button
          variant="default"
          size="icon-xs"
          aria-label={`Copy ${command}`}
          onClick={handleCopy}
        >
          {copied ? (
            <Check size={12} className="text-(--green-11)" />
          ) : (
            <Copy size={12} />
          )}
        </Button>
      </Tooltip>
    </span>
  );
}
