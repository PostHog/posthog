import { Check, Code, Copy, Eye } from "@phosphor-icons/react";
import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { type ReactElement, type ReactNode, useState } from "react";

interface DocumentPreviewHeaderProps {
  label: string;
  /** Version stepper rendered beside the label (see ArtifactVersionNav). */
  versionNav?: ReactNode;
  content: string;
  getContent?: () => string;
  showRendered: boolean;
  onToggleRendered?: () => void;
  actions?: ReactNode;
  canEdit?: boolean;
  editing?: boolean;
  saving?: boolean;
  onEdit?: () => void;
  onCancel?: () => void;
  onSave?: () => void;
}

export function DocumentPreviewHeader({
  label,
  versionNav,
  content,
  getContent,
  showRendered,
  onToggleRendered,
  actions,
  canEdit = false,
  editing = false,
  saving = false,
  onEdit,
  onCancel,
  onSave,
}: DocumentPreviewHeaderProps): ReactElement {
  const [copied, setCopied] = useState(false);

  const handleCopySource = (): void => {
    void navigator.clipboard.writeText(getContent?.() ?? content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="flex h-10 shrink-0 items-center justify-between gap-2 border-b border-b-(--gray-6) px-3">
      <div className="flex min-w-0 items-center gap-2">
        <span className="truncate font-[var(--code-font-family)] text-[13px] text-muted-foreground">
          {label}
        </span>
        {versionNav}
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {actions}
        {!editing && onToggleRendered && (
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
        )}
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
        {editing ? (
          <>
            <Button
              size="sm"
              variant="outline"
              disabled={saving}
              onClick={onCancel}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              variant="primary"
              loading={saving}
              onClick={onSave}
            >
              Save
            </Button>
          </>
        ) : (
          canEdit && (
            <Button size="sm" variant="outline" onClick={onEdit}>
              Edit
            </Button>
          )
        )}
      </div>
    </div>
  );
}
