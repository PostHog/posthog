import { Check, Code, Copy, Eye } from "@phosphor-icons/react";
import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { type ReactNode, useState } from "react";

export function DocumentPreviewHeader({
  label,
  content,
  showRendered,
  onToggleRendered,
  actions,
}: {
  label: string;
  content: string;
  showRendered: boolean;
  onToggleRendered: () => void;
  actions?: ReactNode;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopySource = () => {
    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="flex shrink-0 items-center justify-between border-b border-b-(--gray-6) px-3 py-2">
      <span className="font-[var(--code-font-family)] text-[13px] text-muted-foreground">
        {label}
      </span>
      <div className="flex items-center gap-1">
        {actions}
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                size="icon"
                variant="default"
                onClick={onToggleRendered}
                aria-label={showRendered ? "View source" : "View preview"}
              >
                {showRendered ? <Code size={14} /> : <Eye size={14} />}
              </Button>
            }
          />
          <TooltipContent>
            {showRendered ? "View source" : "View preview"}
          </TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                size="icon"
                variant="default"
                onClick={handleCopySource}
                aria-label="Copy source"
              >
                {copied ? <Check size={14} /> : <Copy size={14} />}
              </Button>
            }
          />
          <TooltipContent>{copied ? "Copied" : "Copy source"}</TooltipContent>
        </Tooltip>
      </div>
    </div>
  );
}
