import {
  ChartLineIcon,
  FileTextIcon,
  FlagIcon,
  FlaskIcon,
  FolderIcon,
  GithubLogoIcon,
  GitPullRequestIcon,
  PulseIcon,
  TerminalIcon,
  WarningIcon,
  XIcon,
} from "@phosphor-icons/react";
import { Chip, cn } from "@posthog/quill";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { getObjectKind } from "@posthog/ui/utils/objectKinds";
import { type NodeViewProps, NodeViewWrapper } from "@tiptap/react";
import { usePasteUndoStore } from "../pasteUndoStore";
import type { ChipType, MentionChipAttrs } from "./MentionChipNode";

const chipBase = "group/chip relative top-px active:translate-y-0";

const selectedRing = "border-ring/50 ring-[1px] ring-ring/50";

const typeIconMap: Record<ChipType, React.ComponentType<{ size: number }>> = {
  file: FileTextIcon,
  folder: FolderIcon,
  command: TerminalIcon,
  github_issue: GithubLogoIcon,
  github_pr: GitPullRequestIcon,
  error: WarningIcon,
  experiment: FlaskIcon,
  insight: ChartLineIcon,
  feature_flag: FlagIcon,
  posthog_object: PulseIcon,
};

function IconCloseButton({
  type,
  iconSize,
  objectKind,
  onRemove,
}: {
  type: ChipType;
  iconSize: number;
  objectKind?: MentionChipAttrs["objectKind"];
  onRemove: () => void;
}) {
  const Icon =
    type === "posthog_object" && objectKind
      ? getObjectKind(objectKind).icon
      : typeIconMap[type] || FileTextIcon;

  return (
    <button
      type="button"
      tabIndex={-1}
      className={cn(
        "relative inline-flex shrink-0 cursor-pointer items-center justify-center border-none bg-transparent p-0",
        iconSize > 10 ? "size-4" : "size-3.5",
      )}
      onClick={(e) => {
        e.stopPropagation();
        onRemove();
      }}
    >
      <span className="ease pointer-events-none absolute inset-0 flex items-center justify-center opacity-50 transition-opacity duration-150 group-hover/chip:opacity-0 motion-reduce:transition-none">
        <Icon size={iconSize} />
      </span>
      <span className="ease pointer-events-none absolute inset-0 flex items-center justify-center opacity-0 transition-opacity duration-150 group-hover/chip:opacity-100 motion-reduce:transition-none">
        <XIcon size={iconSize} />
      </span>
    </button>
  );
}

function DefaultChip({
  type,
  id,
  label,
  objectKind,
  chipId,
  pastedText,
  selected,
  onRemove,
}: {
  type: string;
  id: string;
  label: string;
  objectKind?: MentionChipAttrs["objectKind"];
  chipId: string | null;
  pastedText: boolean;
  selected: boolean;
  onRemove: () => void;
}) {
  const undoableChipId = usePasteUndoStore((state) => state.undoableChipId);
  const canUndoPaste =
    pastedText && chipId !== null && chipId === undoableChipId;
  const isCommand = type === "command";
  const prefix = isCommand ? "/" : type === "posthog_object" ? "" : "@";
  const isFile = type === "file";
  const isFolder = type === "folder";
  const isGithubRef = type === "github_issue" || type === "github_pr";
  const isPr = type === "github_pr";
  const canOpenUrl = isGithubRef && /^https:\/\//.test(id);

  // A skill reads as part of the sentence being written, not as an object
  // attached to it, so it stays plain text rather than taking a chip's border
  // and remove button. Selecting it — arrowing onto it, or the backspace that
  // is about to delete it — turns the run destructive, which is the only
  // warning left once there is no × to aim at.
  if (isCommand) {
    return (
      <span
        contentEditable={false}
        className={cn(
          "cli-slash-command cursor-default select-all bg-fill-hover px-0.5 font-medium",
          selected
            ? "rounded-xs bg-destructive text-destructive-foreground"
            : "text-primary",
        )}
      >
        {prefix}
        {label}
      </span>
    );
  }

  const chipContent = (
    <Chip
      size={isPr ? "sm" : "xs"}
      contentEditable={false}
      onClick={canOpenUrl ? () => window.open(id, "_blank") : undefined}
      className={`${chipBase} ${isPr ? "pl-1.5" : "pl-1"} max-w-full whitespace-nowrap ${isGithubRef ? "cursor-pointer!" : "cursor-default! active:translate-y-0!"} ${isCommand ? "cli-slash-command" : "cli-file-mention"} ${selected ? selectedRing : ""}`}
    >
      <IconCloseButton
        type={type as ChipType}
        iconSize={isPr ? 12 : 10}
        objectKind={objectKind}
        onRemove={onRemove}
      />
      {isGithubRef ? (
        <span className="min-w-0 truncate">{label}</span>
      ) : (
        `${prefix}${label}`
      )}
    </Chip>
  );

  if (isFile || isFolder) {
    return (
      <Tooltip content={canUndoPaste ? "Paste again to expand as text" : id}>
        {chipContent}
      </Tooltip>
    );
  }

  return chipContent;
}

export function MentionChipView({
  node,
  getPos,
  editor,
  selected,
}: NodeViewProps) {
  const { type, id, label, objectKind, pastedText, chipId } =
    node.attrs as MentionChipAttrs;

  const handleRemove = () => {
    const pos = getPos();
    if (pos == null) return;
    editor
      .chain()
      .focus()
      .deleteRange({ from: pos, to: pos + node.nodeSize })
      .run();
  };

  return (
    <NodeViewWrapper as="span" className="inline">
      <DefaultChip
        type={type}
        id={id}
        label={label}
        objectKind={objectKind}
        chipId={chipId ?? null}
        pastedText={pastedText}
        selected={selected}
        onRemove={handleRemove}
      />
    </NodeViewWrapper>
  );
}
