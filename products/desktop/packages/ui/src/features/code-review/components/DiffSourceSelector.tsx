import {
  CaretDown,
  GitBranch,
  GitPullRequest,
  HardDrives,
} from "@phosphor-icons/react";
import type { ResolvedDiffSource } from "@posthog/core/code-review/resolveDiffSource";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@posthog/quill";
import { useDiffViewerStore } from "@posthog/ui/features/code-editor/diffViewerStore";

interface DiffSourceSelectorProps {
  taskId: string;
  effectiveSource: ResolvedDiffSource;
  branchAvailable: boolean;
  prSourceAvailable: boolean;
  defaultBranch: string | null;
}

export function DiffSourceSelector({
  taskId,
  effectiveSource,
  branchAvailable,
  prSourceAvailable,
  defaultBranch,
}: DiffSourceSelectorProps) {
  const setDiffSource = useDiffViewerStore((s) => s.setDiffSource);

  const anyAlternative = branchAvailable || prSourceAvailable;
  if (!anyAlternative) return null;

  const branchLabel = defaultBranch ? `Branch vs. ${defaultBranch}` : "Branch";
  const { icon: Icon, label: triggerLabel } = (() => {
    if (effectiveSource === "pr") return { icon: GitPullRequest, label: "PR" };
    if (effectiveSource === "branch")
      return { icon: GitBranch, label: branchLabel };
    return { icon: HardDrives, label: "Local" };
  })();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            size="sm"
            variant="default"
            className="rounded-xs"
            aria-label="Diff source"
          >
            <Icon size={12} />
            <span className="whitespace-nowrap">{triggerLabel}</span>
            <CaretDown size={10} weight="bold" />
          </Button>
        }
      />
      <DropdownMenuContent
        align="end"
        side="bottom"
        sideOffset={6}
        className="min-w-[160px]"
      >
        <DropdownMenuItem onClick={() => setDiffSource(taskId, "local")}>
          <HardDrives size={12} />
          Local changes
        </DropdownMenuItem>
        {branchAvailable && defaultBranch && (
          <DropdownMenuItem onClick={() => setDiffSource(taskId, "branch")}>
            <GitBranch size={12} />
            {branchLabel}
          </DropdownMenuItem>
        )}
        {prSourceAvailable && (
          <DropdownMenuItem onClick={() => setDiffSource(taskId, "pr")}>
            <GitPullRequest size={12} />
            Pull request
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
