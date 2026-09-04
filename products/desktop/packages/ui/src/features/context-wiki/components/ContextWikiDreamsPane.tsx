import { MoonIcon, WarningCircleIcon } from "@phosphor-icons/react";
import { processFile } from "@pierre/diffs";
import { FileDiff } from "@pierre/diffs/react";
import type {
  ContextWikiActiveDreamRun,
  ContextWikiDreamFile,
  ContextWikiDreamRun,
} from "@posthog/api-client/posthog-client";
import {
  Badge,
  Button,
  cn,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
  Text,
} from "@posthog/quill";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { DIFFS_HIGHLIGHTER_OPTIONS } from "@posthog/ui/features/sessions/diffHighlighterOptions";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { useMemo, useState } from "react";
import type { Components } from "react-markdown";
import { useThemeStore } from "../../../shell/themeStore";
import {
  useContextWikiDream,
  useContextWikiDreams,
} from "../hooks/useContextWiki";
import { firstSummaryLine } from "./contextWikiDreams";

const dreamMarkdownComponents: Partial<Components> = {
  img: ({ alt }) => (
    <span className="text-[13px] text-gray-10">
      Remote image blocked{alt ? `: ${alt}` : ""}
    </span>
  ),
};

/**
 * The dreaming history: every nightly synthesis run the wiki landed, newest
 * first. Selecting a run shows the summary the agent wrote and the diff it
 * landed, read from the wiki's git history.
 */
export function ContextWikiDreamsPane() {
  const { data, isLoading, error, refetch } = useContextWikiDreams();
  const [selectedSha, setSelectedSha] = useState<string | null>(null);

  const dreams = useMemo(() => data?.dreams ?? [], [data]);
  const activeRun = data?.active_run ?? null;
  const effectiveSha =
    selectedSha && dreams.some((dream) => dream.sha === selectedSha)
      ? selectedSha
      : (dreams[0]?.sha ?? null);
  const selectedRun = dreams.find((dream) => dream.sha === effectiveSha);

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner className="size-5" />
      </div>
    );
  }

  if (error) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <WarningCircleIcon size={28} />
          </EmptyMedia>
          <EmptyTitle>Couldn't load the dream runs</EmptyTitle>
          <EmptyDescription>{error.message}</EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button variant="outline" size="default" onClick={() => refetch()}>
            Try again
          </Button>
        </EmptyContent>
      </Empty>
    );
  }

  if (!selectedRun && !activeRun) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <MoonIcon size={28} />
          </EmptyMedia>
          <EmptyTitle>No dream runs yet</EmptyTitle>
          <EmptyDescription>
            Every night a dreaming agent reads recent activity and lands what it
            learned into the wiki. Its runs will show up here.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <div className="flex h-full min-h-0">
      <div className="flex w-72 shrink-0 flex-col overflow-y-auto border-(--gray-5) border-r">
        {activeRun ? <ActiveDreamListItem run={activeRun} /> : null}
        {dreams.map((dream) => (
          <DreamListItem
            key={dream.sha}
            dream={dream}
            selected={dream.sha === effectiveSha}
            onSelect={() => setSelectedSha(dream.sha)}
          />
        ))}
      </div>
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {selectedRun ? (
          <DreamDetail key={selectedRun.sha} run={selectedRun} />
        ) : (
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <MoonIcon size={28} />
              </EmptyMedia>
              <EmptyTitle>Dream in progress</EmptyTitle>
              <EmptyDescription>
                This run will appear in the history after it lands its changes.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}
      </div>
    </div>
  );
}

const ACTIVE_DREAM_LABELS: Record<
  ContextWikiActiveDreamRun["run_status"],
  string
> = {
  not_started: "Preparing dream",
  queued: "Dream queued",
  in_progress: "Dreaming now",
};

function ActiveDreamListItem({ run }: { run: ContextWikiActiveDreamRun }) {
  return (
    <div className="flex flex-col gap-1 border-(--gray-5) border-b bg-(--gray-2) px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Spinner className="size-3.5" />
          <Text size="sm" weight="medium">
            {ACTIVE_DREAM_LABELS[run.run_status]}
          </Text>
        </div>
        <RelativeTimestamp timestamp={run.started_at} />
      </div>
      <Text size="xs" variant="muted">
        Reading recent activity and updating the wiki.
      </Text>
    </div>
  );
}

function DreamListItem({
  dream,
  selected,
  onSelect,
}: {
  dream: ContextWikiDreamRun;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "flex flex-col gap-1 border-(--gray-5) border-b px-4 py-3 text-left hover:bg-(--gray-2)",
        selected && "bg-(--gray-2)",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <Text size="sm" weight="medium">
          {dream.date}
        </Text>
        <RelativeTimestamp timestamp={dream.committed_at} />
      </div>
      <div className="flex items-center gap-2">
        <DreamStats dream={dream} />
      </div>
      {dream.summary ? (
        <Text size="xs" variant="muted" className="line-clamp-2">
          {firstSummaryLine(dream.summary)}
        </Text>
      ) : null}
    </button>
  );
}

function DreamStats({ dream }: { dream: ContextWikiDreamRun }) {
  const parts: {
    label: string;
    variant: "success" | "info" | "destructive";
  }[] = [];
  if (dream.pages_added > 0) {
    parts.push({ label: `+${dream.pages_added}`, variant: "success" });
  }
  if (dream.pages_modified > 0) {
    parts.push({ label: `~${dream.pages_modified}`, variant: "info" });
  }
  if (dream.pages_deleted > 0) {
    parts.push({ label: `−${dream.pages_deleted}`, variant: "destructive" });
  }
  if (parts.length === 0) {
    return (
      <Text size="xs" variant="muted">
        No page changes
      </Text>
    );
  }
  return (
    <div className="flex items-center gap-1">
      {parts.map((part) => (
        <Badge key={part.label} variant={part.variant}>
          {part.label}
        </Badge>
      ))}
    </div>
  );
}

function DreamDetail({ run }: { run: ContextWikiDreamRun }) {
  const {
    data: detail,
    isLoading,
    error,
    refetch,
  } = useContextWikiDream(run.sha);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto">
      <div className="flex flex-col gap-1 border-(--gray-5) border-b px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <Text size="base" weight="semibold">
            Dream run: {run.date}
          </Text>
          <RelativeTimestamp timestamp={run.committed_at} />
        </div>
        <code className="truncate text-[11px] text-gray-10">{run.sha}</code>
      </div>
      {run.summary ? (
        <div className="border-(--gray-5) border-b p-4 text-[13px]">
          <MarkdownRenderer
            content={run.summary}
            componentsOverride={dreamMarkdownComponents}
          />
        </div>
      ) : null}
      <div className="flex flex-col gap-3 p-4">
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Spinner className="size-5" />
          </div>
        ) : error ? (
          <div className="flex flex-col items-center gap-2 py-8 text-[13px] text-gray-10">
            <span>Couldn't load this run's changes: {error.message}</span>
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              Try again
            </Button>
          </div>
        ) : detail && detail.files.length > 0 ? (
          detail.files.map((file) => (
            <DreamFileDiffView key={file.path} file={file} />
          ))
        ) : (
          <Text size="sm" variant="muted">
            This run landed without changing any pages.
          </Text>
        )}
      </div>
    </div>
  );
}

function DreamFileDiffView({ file }: { file: ContextWikiDreamFile }) {
  const isDarkMode = useThemeStore((s) => s.isDarkMode);
  const fileDiff = useMemo(() => {
    if (!file.patch) return undefined;
    try {
      return processFile(file.patch, { isGitDiff: true });
    } catch {
      return undefined;
    }
  }, [file.patch]);
  const options = useMemo(
    () => ({
      ...DIFFS_HIGHLIGHTER_OPTIONS,
      diffStyle: "unified" as const,
      overflow: "wrap" as const,
      themeType: (isDarkMode ? "dark" : "light") as "dark" | "light",
    }),
    [isDarkMode],
  );

  return (
    <div className="overflow-hidden rounded-(--radius-2) border border-(--gray-5)">
      <div className="flex items-center justify-between gap-2 border-(--gray-5) border-b bg-(--gray-2) px-3 py-1.5">
        <code className="truncate text-[12px]">{file.path}</code>
        <Badge
          variant={
            file.status === "added"
              ? "success"
              : file.status === "deleted"
                ? "destructive"
                : "info"
          }
        >
          {file.status}
        </Badge>
      </div>
      {fileDiff ? (
        <>
          <FileDiff fileDiff={fileDiff} options={options} />
          {file.truncated ? (
            <div className="border-(--gray-5) border-t bg-(--gray-2) px-3 py-1.5 text-(--gray-10) text-[12px]">
              This patch was too large to show in full.
            </div>
          ) : null}
        </>
      ) : (
        <div className="bg-(--gray-2) px-3 py-2 text-(--gray-10) text-[12px]">
          {file.truncated
            ? "This patch was too large to show in full."
            : "No diff available for this file."}
        </div>
      )}
    </div>
  );
}
