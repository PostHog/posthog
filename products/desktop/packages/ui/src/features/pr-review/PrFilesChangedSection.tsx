import { CheckIcon, GitBranchIcon, GitDiffIcon } from "@phosphor-icons/react";
import { Button, Spinner, ToggleGroup, ToggleGroupItem } from "@posthog/quill";
import {
  useDiffViewerStore,
  type ViewMode,
} from "@posthog/ui/features/code-editor/diffViewerStore";
import { PatchedFileDiff } from "@posthog/ui/features/code-review/components/PatchedFileDiff";
import { useDiffOptions } from "@posthog/ui/features/code-review/reviewShellParts";
import { usePrChangedFiles } from "@posthog/ui/features/git-interaction/useGitQueries";
import { DetailSection } from "@posthog/ui/features/inbox/components/DetailSection";
import { NestedButton } from "@posthog/ui/primitives/NestedButton";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { type ReactNode, useMemo, useRef, useState } from "react";
import {
  fileViewedFingerprint,
  isFileViewed,
  usePrViewedFilesStore,
} from "./prViewedFilesStore";
import { usePrInfo } from "./usePrInfo";

interface PrFilesChangedSectionProps {
  prUrl: string;
  /**
   * Flat layout for a dedicated tab, like the web detail's Files changed
   * page: a plain header row and the per-file diffs as siblings, instead of
   * one card wrapping every diff.
   */
  bare?: boolean;
}

/**
 * GitHub-style "Files changed" list for a PR: one collapsible diff per file,
 * all expanded by default so the tab opens straight onto the changes. An
 * expanded file gets a footer row with the "Viewed" toggle; marking a file
 * viewed folds it back up.
 */
export function PrFilesChangedSection({
  prUrl,
  bare = false,
}: PrFilesChangedSectionProps) {
  const filesQuery = usePrChangedFiles(prUrl);
  const diffOptions = useDiffOptions();
  const viewMode = useDiffViewerStore((s) => s.viewMode);
  const setViewMode = useDiffViewerStore((s) => s.setViewMode);
  // The branch pill only renders in the tab layout; skip the fetch otherwise.
  const prInfoQuery = usePrInfo(bare ? prUrl : null);
  const headRefName = prInfoQuery.data?.headRefName ?? null;
  const viewedByPr = usePrViewedFilesStore((s) => s.viewedByPr);
  const markViewed = usePrViewedFilesStore((s) => s.markViewed);
  const unmarkViewed = usePrViewedFilesStore((s) => s.unmarkViewed);

  // Per-file collapse overrides on top of a section-wide baseline, so
  // expand/collapse-all is one state flip instead of a map rebuild.
  const [baselineCollapsed, setBaselineCollapsed] = useState(false);
  const [collapseOverrides, setCollapseOverrides] = useState<
    Map<string, boolean>
  >(new Map());
  const fileContainerRefs = useRef<Map<string, HTMLDivElement> | null>(null);
  // Lazy init so the Map isn't rebuilt (and discarded) on every render.
  if (fileContainerRefs.current === null) {
    fileContainerRefs.current = new Map();
  }
  const fileContainers = fileContainerRefs.current;

  const files = filesQuery.data;

  const viewedCount = useMemo(
    () =>
      (files ?? []).filter((file) => isFileViewed(viewedByPr, prUrl, file))
        .length,
    [files, viewedByPr, prUrl],
  );

  const messageState = (body: ReactNode) =>
    bare ? (
      <div className="py-3 text-[12px] text-gray-10">{body}</div>
    ) : (
      <DetailSection Icon={GitDiffIcon} title="Files changed">
        <div className="py-3 text-[12px] text-gray-10">{body}</div>
      </DetailSection>
    );

  if (filesQuery.isLoading) {
    return messageState(
      <span className="flex items-center gap-2">
        <Spinner />
        Loading changed files…
      </span>,
    );
  }

  if (filesQuery.isError || !files) {
    return messageState(
      "Couldn't load the changed files for this pull request.",
    );
  }

  if (files.length === 0) {
    return messageState("No changed files.");
  }

  const isCollapsed = (path: string) =>
    collapseOverrides.get(path) ?? baselineCollapsed;
  const allExpanded = files.every((file) => !isCollapsed(file.path));

  const setAllCollapsed = (collapsed: boolean) => {
    setBaselineCollapsed(collapsed);
    setCollapseOverrides(new Map());
  };

  const headerControls = (
    <span className="flex items-center gap-2">
      <span className="cursor-default select-none text-[11px] text-gray-10 tabular-nums">
        {viewedCount} / {files.length} viewed
      </span>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => setAllCollapsed(allExpanded)}
      >
        {allExpanded ? "Collapse all" : "Expand all"}
      </Button>
    </span>
  );

  const fileList = (
    <div className="flex flex-col gap-3">
      {files.map((file) => {
        const viewed = isFileViewed(viewedByPr, prUrl, file);
        const collapsed = isCollapsed(file.path);
        const setCollapsed = (next: boolean) =>
          setCollapseOverrides((prev) => new Map(prev).set(file.path, next));
        // Folding removes a diff that can be taller than the viewport,
        // which would leave it staring at blank space below — scroll the
        // folded file back into view. rAF runs after React commits the
        // collapse but before the browser paints.
        const collapseAndReveal = () => {
          setCollapsed(true);
          requestAnimationFrame(() => {
            fileContainers.get(file.path)?.scrollIntoView({ block: "nearest" });
          });
        };
        const handleViewedChange = (next: boolean) => {
          if (next) {
            markViewed(prUrl, file.path, fileViewedFingerprint(file));
            // Fold the file away once it's read, like GitHub.
            if (!collapsed) collapseAndReveal();
          } else {
            unmarkViewed(prUrl, file.path);
          }
        };
        return (
          <div
            key={file.path}
            ref={(el) => {
              if (el) fileContainers.set(file.path, el);
              else fileContainers.delete(file.path);
            }}
            className="overflow-hidden rounded-md border border-(--gray-5)"
          >
            <PatchedFileDiff
              file={file}
              taskId={prUrl}
              options={diffOptions}
              collapsed={collapsed}
              onToggle={() => setCollapsed(!collapsed)}
              externalUrl={`${prUrl}/files`}
              prUrl={prUrl}
              headerTrailing={
                collapsed ? (
                  <ViewedToggle viewed={viewed} onChange={handleViewedChange} />
                ) : undefined
              }
            />
            {!collapsed && (
              <div className="flex items-center justify-end gap-1 border-t border-t-(--gray-5) bg-(--gray-2) px-3 py-[4px]">
                <button
                  type="button"
                  onClick={collapseAndReveal}
                  className="cursor-pointer rounded border-0 bg-transparent px-[6px] py-[2px] text-(--accent-9) text-[11px] hover:bg-gray-4"
                >
                  Collapse
                </button>
                <ViewedToggle viewed={viewed} onChange={handleViewedChange} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );

  if (bare) {
    return (
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="flex min-w-0 items-center gap-2.5">
            <span className="cursor-default select-none whitespace-nowrap font-semibold text-[13px] text-gray-12">
              {files.length} file{files.length === 1 ? "" : "s"} changed
            </span>
            {headRefName && (
              <button
                type="button"
                onClick={() => openExternalUrl(prUrl)}
                className="inline-flex min-w-0 cursor-pointer items-center gap-1.5 rounded-full border border-(--accent-8) px-2.5 py-1 font-mono text-(--accent-11) text-[11px] hover:bg-(--accent-a3)"
                title="Open the pull request on GitHub"
              >
                <GitBranchIcon size={11} className="shrink-0" />
                <span className="truncate">{headRefName}</span>
              </button>
            )}
          </span>
          <span className="flex items-center gap-2">
            <ToggleGroup
              aria-label="Diff layout"
              value={[viewMode]}
              onValueChange={(next: string[]) => {
                // Pressing the active item would otherwise clear the group —
                // a layout is always on, so ignore the empty result.
                const mode = next[0];
                if (mode === "unified" || mode === "split") {
                  setViewMode(mode as ViewMode);
                }
              }}
            >
              <ToggleGroupItem value="unified">Unified</ToggleGroupItem>
              <ToggleGroupItem value="split">Split</ToggleGroupItem>
            </ToggleGroup>
            {headerControls}
          </span>
        </div>
        {fileList}
      </div>
    );
  }

  return (
    <DetailSection
      Icon={GitDiffIcon}
      title={`Files changed (${files.length})`}
      rightSlot={headerControls}
    >
      {fileList}
    </DetailSection>
  );
}

/**
 * NestedButton because the collapsed placement sits inside the file header
 * row, which is itself a `<button>`; it works the same in the plain footer.
 */
function ViewedToggle({
  viewed,
  onChange,
}: {
  viewed: boolean;
  onChange: (viewed: boolean) => void;
}) {
  return (
    <NestedButton
      aria-label={viewed ? "Mark as not viewed" : "Mark as viewed"}
      aria-pressed={viewed}
      onActivate={() => onChange(!viewed)}
      className="inline-flex shrink-0 cursor-pointer items-center gap-[5px] rounded px-[6px] py-[2px] text-[11px] text-gray-11 hover:bg-gray-4"
    >
      <span
        className={`inline-flex h-[13px] w-[13px] items-center justify-center rounded-[3px] border ${
          viewed
            ? "border-(--accent-9) bg-(--accent-9) text-white"
            : "border-(--gray-7)"
        }`}
      >
        {viewed && <CheckIcon size={9} weight="bold" />}
      </span>
      Viewed
    </NestedButton>
  );
}
