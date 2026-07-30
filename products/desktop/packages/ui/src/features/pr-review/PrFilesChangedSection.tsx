import { CheckIcon, GitDiffIcon } from "@phosphor-icons/react";
import { Button, Spinner } from "@posthog/quill";
import { PatchedFileDiff } from "@posthog/ui/features/code-review/components/PatchedFileDiff";
import { useDiffOptions } from "@posthog/ui/features/code-review/reviewShellParts";
import { usePrChangedFiles } from "@posthog/ui/features/git-interaction/useGitQueries";
import { DetailSection } from "@posthog/ui/features/inbox/components/DetailSection";
import { NestedButton } from "@posthog/ui/primitives/NestedButton";
import { useMemo, useRef, useState } from "react";
import {
  fileViewedFingerprint,
  isFileViewed,
  usePrViewedFilesStore,
} from "./prViewedFilesStore";

interface PrFilesChangedSectionProps {
  prUrl: string;
}

/**
 * GitHub-style "Files changed" list for a PR: one collapsible diff per file,
 * all collapsed by default. An expanded file gets a footer row with the
 * "Viewed" toggle; marking a file viewed folds it back up.
 */
export function PrFilesChangedSection({ prUrl }: PrFilesChangedSectionProps) {
  const filesQuery = usePrChangedFiles(prUrl);
  const diffOptions = useDiffOptions();
  const viewedByPr = usePrViewedFilesStore((s) => s.viewedByPr);
  const markViewed = usePrViewedFilesStore((s) => s.markViewed);
  const unmarkViewed = usePrViewedFilesStore((s) => s.unmarkViewed);

  // Per-file collapse overrides on top of a section-wide baseline, so
  // expand/collapse-all is one state flip instead of a map rebuild.
  const [baselineCollapsed, setBaselineCollapsed] = useState(true);
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

  if (filesQuery.isLoading) {
    return (
      <DetailSection Icon={GitDiffIcon} title="Files changed">
        <div className="flex items-center gap-2 py-3 text-[12px] text-gray-10">
          <Spinner />
          Loading changed files…
        </div>
      </DetailSection>
    );
  }

  if (filesQuery.isError || !files) {
    return (
      <DetailSection Icon={GitDiffIcon} title="Files changed">
        <div className="py-3 text-[12px] text-gray-10">
          Couldn't load the changed files for this pull request.
        </div>
      </DetailSection>
    );
  }

  if (files.length === 0) {
    return (
      <DetailSection Icon={GitDiffIcon} title="Files changed">
        <div className="py-3 text-[12px] text-gray-10">No changed files.</div>
      </DetailSection>
    );
  }

  const isCollapsed = (path: string) =>
    collapseOverrides.get(path) ?? baselineCollapsed;
  const allExpanded = files.every((file) => !isCollapsed(file.path));

  const setAllCollapsed = (collapsed: boolean) => {
    setBaselineCollapsed(collapsed);
    setCollapseOverrides(new Map());
  };

  return (
    <DetailSection
      Icon={GitDiffIcon}
      title={`Files changed (${files.length})`}
      rightSlot={
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
      }
    >
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
              fileContainers
                .get(file.path)
                ?.scrollIntoView({ block: "nearest" });
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
                    <ViewedToggle
                      viewed={viewed}
                      onChange={handleViewedChange}
                    />
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
