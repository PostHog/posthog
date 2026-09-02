import {
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
import { CheckIcon } from "@radix-ui/react-icons";
import {
  Box,
  Button,
  Checkbox,
  Dialog,
  Flex,
  IconButton,
  Spinner,
  Text,
  TextArea,
  TextField,
} from "@radix-ui/themes";
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
    <Box className="max-h-[200px] overflow-auto rounded-(--radius-2) border border-(--red-6) bg-(--red-2)">
      <Flex direction="column" gap="2" p="2">
        <Flex justify="between" align="start" gap="2">
          <Text
            color="red"
            className="flex-1 whitespace-pre-wrap break-words font-[var(--code-font-family)] text-[13px]"
          >
            {error}
          </Text>
          <Flex gap="1" className="shrink-0">
            {onFixWithAgent && (
              <Tooltip content="Fix with Agent">
                <IconButton
                  size="1"
                  variant="ghost"
                  color="gray"
                  onClick={onFixWithAgent}
                >
                  <Sparkle size={12} />
                </IconButton>
              </Tooltip>
            )}
            <Tooltip content={copied ? "Copied!" : "Copy error"}>
              <IconButton
                size="1"
                variant="ghost"
                color="gray"
                onClick={handleCopy}
              >
                <Copy size={12} weight={copied ? "fill" : "regular"} />
              </IconButton>
            </Tooltip>
          </Flex>
        </Flex>
      </Flex>
    </Box>
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
      <IconButton
        size="1"
        variant="ghost"
        color="gray"
        onClick={onClick}
        disabled={isGenerating || disabled}
      >
        {isGenerating ? <Spinner size="1" /> : <Sparkle size={14} />}
      </IconButton>
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
    <Flex
      align="center"
      gap="2"
      py="1"
      onClick={() => onChange(!checked)}
      className="cursor-pointer"
    >
      <Checkbox
        size="1"
        checked={checked}
        onCheckedChange={(c) => onChange(c === true)}
        onClick={(e) => e.stopPropagation()}
      />
      <Text color="gray" className="text-[13px]">
        Commit all changes
      </Text>
    </Flex>
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
  maxWidth?: string;
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
  maxWidth = "400px",
  hideCancel,
}: GitDialogProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Content maxWidth={maxWidth} size="1">
        <Flex direction="column" gap="3">
          <Flex align="center" gap="2">
            {icon}
            <Text className="font-medium text-sm">{title}</Text>
          </Flex>

          {children}

          {error && <ErrorContainer error={error} />}

          <Flex gap="2" justify="end">
            {!hideCancel && (
              <Dialog.Close>
                <Button size="1" variant="soft" color="gray">
                  Cancel
                </Button>
              </Dialog.Close>
            )}
            <Button
              size="1"
              disabled={buttonDisabled || isSubmitting}
              loading={isSubmitting}
              onClick={onSubmit}
            >
              {buttonLabel}
            </Button>
          </Flex>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}

function InfoRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Flex align="center" justify="between">
      <Text color="gray" className="text-[13px]">
        {label}
      </Text>
      {children}
    </Flex>
  );
}

function BranchBadge({ branch }: { branch: string | null }) {
  return (
    <Tooltip content={branch ?? "Unknown"}>
      <Flex align="center" gap="1" className="min-w-0 max-w-[240px]">
        <GitBranch size={12} className="shrink-0" />
        <Text truncate className="text-[13px]">
          {branch ?? "Unknown"}
        </Text>
      </Flex>
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
    <Box
      role="button"
      onClick={() => !disabled && onSelect()}
      style={{
        background: selected ? "var(--accent-4)" : "var(--gray-2)",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
      }}
      className="flex items-center justify-between border border-(--gray-6) px-[8px] py-[6px]"
    >
      <Flex align="center" gap="2">
        {icon}
        <Text className="font-medium text-[13px]">{label}</Text>
      </Flex>
      {selected && <CheckIcon />}
    </Box>
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
      <Flex direction="column" gap="1">
        <InfoRow label="Branch">
          <BranchBadge branch={branchName} />
        </InfoRow>
        <InfoRow label="Changes">
          <Flex align="center" gap="2">
            <Text color="gray" className="text-[13px]">
              {formatFileCountLabel(
                !!(showCommitAllToggle && !commitAll),
                stagedFileCount ?? 0,
                diffStats.filesChanged,
              )}
            </Text>
            <Text color="green" className="text-[13px]">
              +{diffStats.linesAdded}
            </Text>
            <Text color="red" className="text-[13px]">
              -{diffStats.linesRemoved}
            </Text>
          </Flex>
        </InfoRow>
        {showCommitAllToggle && onCommitAllChange && (
          <CommitAllToggle checked={commitAll} onChange={onCommitAllChange} />
        )}
      </Flex>

      <Flex direction="column" gap="1">
        <Flex align="center" justify="between">
          <Text color="gray" className="text-[13px]">
            Message
          </Text>
          <GenerateButton
            onClick={onGenerateMessage}
            isGenerating={isGeneratingMessage}
            disabled={isSubmitting}
            tooltip="Generate commit message with AI"
          />
        </Flex>
        <TextArea
          value={commitMessage}
          onChange={(e) => onCommitMessageChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (!isSubmitting && !isGeneratingMessage) onContinue();
            }
          }}
          placeholder="Leave empty to generate with AI"
          size="1"
          rows={1}
          autoFocus
        />
      </Flex>

      <Flex direction="column" gap="1">
        <Text color="gray" className="text-[13px]">
          Then
        </Text>
        {options.map((opt) => (
          <SelectableOption
            key={opt.id}
            icon={opt.icon}
            label={opt.label}
            selected={nextStep === opt.id}
            disabled={!!opt.disabledReason}
            disabledReason={opt.disabledReason ?? null}
            onSelect={() => onNextStepChange(opt.id)}
          />
        ))}
      </Flex>
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
        <Text color="gray" className="text-[13px]">
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
      <Text color="gray" className="text-[13px]">
        Create a feature branch to commit changes, push, and create a PR.
      </Text>

      <Flex direction="column" gap="1">
        <Text color="gray" className="text-[13px]">
          Branch name
        </Text>
        <TextField.Root
          value={branchName}
          onChange={(e) => onBranchNameChange(e.target.value)}
          onKeyDown={(e) => {
            if (
              e.key === "Enter" &&
              branchName.trim() &&
              !error &&
              !isSubmitting
            ) {
              e.preventDefault();
              onConfirm();
            }
          }}
          placeholder="feature-name"
          size="1"
          autoFocus
        />
        {error && (
          <Text color="red" className="text-[13px]">
            {error}
          </Text>
        )}
      </Flex>
    </GitDialog>
  );
}
