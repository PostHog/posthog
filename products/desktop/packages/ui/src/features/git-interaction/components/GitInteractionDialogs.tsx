import {
  Check,
  CheckCircle,
  CloudArrowUp,
  Copy,
  GitBranch,
  GitCommit,
  GitFork,
  Sparkle,
} from "@phosphor-icons/react";
import {
  type DiffStats,
  formatFileCountLabel,
} from "@posthog/core/git-interaction/diffStats";
import {
  Button,
  Checkbox,
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Text,
  Textarea,
} from "@posthog/quill";
import type { ReactNode } from "react";
import { useState } from "react";
import { Tooltip } from "../../../primitives/Tooltip";

const ICON_SIZE = 14;

export function ErrorContainer({
  error,
  onFixWithAgent,
}: {
  error: string;
  onFixWithAgent?: () => void;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(error);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="max-h-[200px] overflow-auto rounded-(--radius-2) border border-(--red-6) bg-(--red-2) p-2">
      <div className="flex items-start justify-between gap-2">
        <Text
          variant="destructive"
          size="xs"
          className="flex-1 whitespace-pre-wrap break-words font-[var(--code-font-family)]"
        >
          {error}
        </Text>
        <div className="flex shrink-0 gap-1">
          {onFixWithAgent && (
            <Tooltip content="Fix with Agent">
              <Button
                size="icon-xs"
                variant="default"
                aria-label="Fix with Agent"
                onClick={onFixWithAgent}
              >
                <Sparkle />
              </Button>
            </Tooltip>
          )}
          <Tooltip content={copied ? "Copied!" : "Copy error"}>
            <Button
              size="icon-xs"
              variant="default"
              aria-label={copied ? "Copied!" : "Copy error"}
              onClick={handleCopy}
            >
              <Copy weight={copied ? "fill" : "regular"} />
            </Button>
          </Tooltip>
        </div>
      </div>
    </div>
  );
}

export function GenerateButton({
  onClick,
  isGenerating,
  disabled = false,
  tooltip = "Generate with AI",
}: {
  onClick: () => void;
  isGenerating: boolean;
  disabled?: boolean;
  tooltip?: string;
}) {
  return (
    <Tooltip content={tooltip}>
      <Button
        size="icon-xs"
        variant="default"
        aria-label={tooltip}
        onClick={onClick}
        disabled={isGenerating || disabled}
        loading={isGenerating}
      >
        <Sparkle />
      </Button>
    </Tooltip>
  );
}

export function CommitAllToggle({
  checked,
  onChange,
}: {
  checked?: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div className="flex items-center gap-2 py-1">
      <Checkbox
        id="commit-all-changes"
        size="sm"
        checked={checked}
        onCheckedChange={(value) => onChange(value === true)}
      />
      <Label
        htmlFor="commit-all-changes"
        className="text-muted-foreground text-xs"
      >
        Commit all changes
      </Label>
    </div>
  );
}

interface GitDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  icon: ReactNode;
  title: string;
  children: ReactNode;
  error: string | null;
  buttonLabel: string;
  buttonDisabled?: boolean;
  isSubmitting: boolean;
  onSubmit: () => void;
  hideCancel?: boolean;
}

export function GitDialog({
  open,
  onOpenChange,
  icon,
  title,
  children,
  error,
  buttonLabel,
  buttonDisabled,
  isSubmitting,
  onSubmit,
  hideCancel,
}: GitDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent showCloseButton={false} className="sm:max-w-[400px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {icon}
            {title}
          </DialogTitle>
        </DialogHeader>

        <DialogBody viewportClassName="flex flex-col gap-3">
          {children}
          {error && <ErrorContainer error={error} />}
        </DialogBody>

        <DialogFooter>
          {!hideCancel && (
            <DialogClose render={<Button size="sm" variant="outline" />}>
              Cancel
            </DialogClose>
          )}
          <Button
            size="sm"
            variant="primary"
            disabled={buttonDisabled || isSubmitting}
            loading={isSubmitting}
            onClick={onSubmit}
          >
            {buttonLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function InfoRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <Text size="xs" variant="muted">
        {label}
      </Text>
      {children}
    </div>
  );
}

function BranchBadge({ branch }: { branch: string | null }) {
  return (
    <Tooltip content={branch ?? "Unknown"}>
      <div className="flex min-w-0 max-w-[240px] items-center gap-1">
        <GitBranch className="shrink-0" />
        <Text size="xs" className="truncate" render={<span />}>
          {branch ?? "Unknown"}
        </Text>
      </div>
    </Tooltip>
  );
}

interface SelectableOptionProps {
  icon: ReactNode;
  label: string;
  selected: boolean;
  disabled: boolean;
  disabledReason: string | null;
  onSelect: () => void;
}

function SelectableOption({
  icon,
  label,
  selected,
  disabled,
  disabledReason,
  onSelect,
}: SelectableOptionProps) {
  const content = (
    <Button
      variant="outline"
      size="sm"
      left
      disabled={disabled}
      onClick={onSelect}
      className={
        selected
          ? "w-full justify-between rounded-none bg-(--accent-4)"
          : "w-full justify-between rounded-none bg-(--gray-2)"
      }
    >
      <span className="flex items-center gap-2">
        {icon}
        <Text size="xs" weight="medium" render={<span />}>
          {label}
        </Text>
      </span>
      {selected && <Check />}
    </Button>
  );

  if (disabled && disabledReason) {
    return <Tooltip content={disabledReason}>{content}</Tooltip>;
  }
  return content;
}

interface GitCommitDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  branchName: string | null;
  diffStats: DiffStats;
  commitMessage: string;
  onCommitMessageChange: (value: string) => void;
  nextStep: "commit" | "commit-push";
  onNextStepChange: (value: "commit" | "commit-push") => void;
  pushDisabledReason: string | null;
  onContinue: () => void;
  isSubmitting: boolean;
  error: string | null;
  onGenerateMessage: () => void;
  isGeneratingMessage: boolean;
  showCommitAllToggle?: boolean;
  commitAll?: boolean;
  onCommitAllChange?: (value: boolean) => void;
  stagedFileCount?: number;
}

export function GitCommitDialog({
  open,
  onOpenChange,
  branchName,
  diffStats,
  commitMessage,
  onCommitMessageChange,
  nextStep,
  onNextStepChange,
  pushDisabledReason,
  onContinue,
  isSubmitting,
  error,
  onGenerateMessage,
  isGeneratingMessage,
  showCommitAllToggle,
  commitAll,
  onCommitAllChange,
  stagedFileCount,
}: GitCommitDialogProps) {
  const options = [
    {
      id: "commit" as const,
      label: "Commit",
      icon: <GitCommit size={ICON_SIZE} />,
    },
    {
      id: "commit-push" as const,
      label: "Commit and push",
      icon: <CloudArrowUp size={ICON_SIZE} />,
      disabledReason: pushDisabledReason,
    },
  ];

  return (
    <GitDialog
      open={open}
      onOpenChange={onOpenChange}
      icon={<GitCommit size={ICON_SIZE} />}
      title="Commit"
      error={error}
      buttonLabel="Continue"
      buttonDisabled={isGeneratingMessage}
      isSubmitting={isSubmitting}
      onSubmit={onContinue}
    >
      <div className="flex flex-col gap-1">
        <InfoRow label="Branch">
          <BranchBadge branch={branchName} />
        </InfoRow>
        <InfoRow label="Changes">
          <div className="flex items-center gap-2">
            <Text size="xs" variant="muted">
              {formatFileCountLabel(
                !!(showCommitAllToggle && !commitAll),
                stagedFileCount ?? 0,
                diffStats.filesChanged,
              )}
            </Text>
            <Text size="xs" className="text-(--green-11)">
              +{diffStats.linesAdded}
            </Text>
            <Text size="xs" variant="destructive">
              -{diffStats.linesRemoved}
            </Text>
          </div>
        </InfoRow>
        {showCommitAllToggle && onCommitAllChange && (
          <CommitAllToggle checked={commitAll} onChange={onCommitAllChange} />
        )}
      </div>

      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between">
          <Text size="xs" variant="muted">
            Message
          </Text>
          <GenerateButton
            onClick={onGenerateMessage}
            isGenerating={isGeneratingMessage}
            disabled={isSubmitting}
            tooltip="Generate commit message with AI"
          />
        </div>
        <Textarea
          value={commitMessage}
          onChange={(event) => onCommitMessageChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              if (!isSubmitting && !isGeneratingMessage) onContinue();
            }
          }}
          placeholder="Leave empty to generate with AI"
          rows={1}
          autoFocus
        />
      </div>

      <div className="flex flex-col gap-1">
        <Text size="xs" variant="muted">
          Then
        </Text>
        {options.map((option) => (
          <SelectableOption
            key={option.id}
            icon={option.icon}
            label={option.label}
            selected={nextStep === option.id}
            disabled={!!option.disabledReason}
            disabledReason={option.disabledReason ?? null}
            onSelect={() => onNextStepChange(option.id)}
          />
        ))}
      </div>
    </GitDialog>
  );
}

interface GitPushDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  branchName: string | null;
  mode: "push" | "sync" | "publish";
  state: "idle" | "success" | "error";
  error: string | null;
  onConfirm: () => void;
  onClose: () => void;
  isSubmitting: boolean;
}

export function GitPushDialog({
  open,
  onOpenChange,
  branchName,
  mode,
  state,
  error,
  onConfirm,
  onClose,
  isSubmitting,
}: GitPushDialogProps) {
  const config = {
    push: {
      title: "Push changes",
      successTitle: "Push complete",
      button: "Push",
      desc: "Push your latest commits to the remote repository.",
    },
    sync: {
      title: "Sync changes",
      successTitle: "Sync complete",
      button: "Sync",
      desc: "Pull remote changes and push your commits.",
    },
    publish: {
      title: "Publish branch",
      successTitle: "Branch published",
      button: "Publish",
      desc: "Push this branch to the remote repository.",
    },
  }[mode];

  const isSuccess = state === "success";
  const icon = isSuccess ? (
    <CheckCircle size={ICON_SIZE} weight="fill" color="var(--green-9)" />
  ) : (
    <CloudArrowUp size={ICON_SIZE} />
  );

  return (
    <GitDialog
      open={open}
      onOpenChange={onOpenChange}
      icon={icon}
      title={isSuccess ? config.successTitle : config.title}
      error={error}
      buttonLabel={isSuccess ? "Close" : config.button}
      isSubmitting={isSubmitting}
      onSubmit={isSuccess ? onClose : onConfirm}
      hideCancel={isSuccess}
    >
      <InfoRow label="Branch">
        <BranchBadge branch={branchName} />
      </InfoRow>
      {!isSuccess && (
        <Text size="xs" variant="muted">
          {config.desc}
        </Text>
      )}
    </GitDialog>
  );
}

interface GitBranchDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  branchName: string;
  onBranchNameChange: (value: string) => void;
  onConfirm: () => void;
  isSubmitting: boolean;
  error: string | null;
}

export function GitBranchDialog({
  open,
  onOpenChange,
  branchName,
  onBranchNameChange,
  onConfirm,
  isSubmitting,
  error,
}: GitBranchDialogProps) {
  return (
    <GitDialog
      open={open}
      onOpenChange={onOpenChange}
      icon={<GitFork size={ICON_SIZE} />}
      title="New branch"
      error={null}
      buttonLabel="Create"
      buttonDisabled={!branchName.trim() || !!error}
      isSubmitting={isSubmitting}
      onSubmit={onConfirm}
    >
      <Text size="xs" variant="muted">
        Create a feature branch to commit changes, push, and create a PR.
      </Text>

      <div className="flex flex-col gap-1">
        <Text size="xs" variant="muted">
          Branch name
        </Text>
        <Input
          value={branchName}
          onChange={(event) => onBranchNameChange(event.target.value)}
          onKeyDown={(event) => {
            if (
              event.key === "Enter" &&
              branchName.trim() &&
              !error &&
              !isSubmitting
            ) {
              event.preventDefault();
              onConfirm();
            }
          }}
          placeholder="feature-name"
          autoFocus
        />
        {error && (
          <Text size="xs" variant="destructive">
            {error}
          </Text>
        )}
      </div>
    </GitDialog>
  );
}
